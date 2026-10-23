"""Compare the component lock with the current server and decide what may be recorded.

Rules: every component declares a ``MAJOR.MINOR.PATCH`` version; a definition never changes
under a recorded version; a new version is at least the bump its changes need, compared with
the highest recorded version below it; removals are recorded deliberately; default tool
definitions stay within the model-visible token budget; and without a readable lock nothing
can be compared, so writing one is a reviewed decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from opendart_mcp.versioning.changes import bump_level, diff_definition, next_version, parse_version
from opendart_mcp.versioning.levels import Level, required_level
from opendart_mcp.versioning.model import sha256

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from opendart_mcp.versioning.levels import Change
    from opendart_mcp.versioning.model import ComponentRecord, Manifest

type Code = Literal[
    "invalid-version",
    "budget",
    "changed",
    "bump",
    "added",
    "new-version",
    "removed",
    "server",
    "integrity",
    "stale",
    "missing",
    "unreadable",
]
type Versions = dict[str, tuple[str, ComponentRecord]]

FATAL: Final[frozenset[Code]] = frozenset({"invalid-version", "budget"})
"""Findings that ``--update`` never records."""
GUARDED: Final[frozenset[Code]] = frozenset({"changed", "bump", "missing", "unreadable"})
"""Findings that ``--update`` records only with ``--accept-changes``: changes under a recorded
version, short bumps, and a missing or unreadable lock. Without a lock every component looks
new, so recording it would also record changes nobody reviewed, including the first lock."""
_SHOWN_CHANGES: Final = 3


@dataclass(frozen=True, slots=True)
class Finding:
    """A difference between the lock and the server, or a broken rule.

    Attributes:
        code (Code): Category.
        key (str): Component key, ``server``, or ``tools``.
        message (str): What happened and what to do.
        changes (tuple[Change, ...]): Classified definition changes, when compared.
    """

    code: Code
    key: str
    message: str
    changes: tuple[Change, ...] = ()

    def __str__(self) -> str:
        """Render the finding for messages.

        Returns:
            str: ``key: message``.
        """
        return f"{self.key}: {self.message}"


def blocking(findings: Iterable[Finding], *, update: bool, accept: bool) -> list[Finding]:
    """Select the findings that fail a run.

    Args:
        findings (Iterable[Finding]): Review results.
        update (bool): Rewriting the lock rather than checking it.
        accept (bool): Changes under a recorded version, short bumps, and every definition
            recorded in place of a missing or unreadable lock were reviewed.

    Returns:
        list[Finding]: Every finding when checking; otherwise those the update must refuse.
    """
    if not update:
        return list(findings)
    refused = FATAL if accept else FATAL | GUARDED
    return [finding for finding in findings if finding.code in refused]


def _summary(changes: Iterable[Change], level: Level) -> str:
    """Describe the changes that set the required level.

    Args:
        changes (Iterable[Change]): Classified changes.
        level (Level): Required level.

    Returns:
        str: Up to three changes at that level, or a note that only the form changed.
    """
    decisive = [str(change) for change in changes if change.level is level]
    if not decisive:
        return f"{level.name}: equivalent definitions written differently"
    shown = "; ".join(decisive[:_SHOWN_CHANGES])
    more = len(decisive) - _SHOWN_CHANGES
    return f"{level.name}: {shown}" + (f"; and {more} more" if more > 0 else "")


def _version_findings(manifest: Manifest) -> list[Finding]:
    """Require a ``MAJOR.MINOR.PATCH`` version on every component.

    Args:
        manifest (Manifest): Current server manifest.

    Returns:
        list[Finding]: One finding per component without a valid version.
    """
    return [
        Finding(
            "invalid-version",
            key,
            'declares no version; add version="1.0.0"'
            if record.version is None
            else f"version {record.version!r} is not MAJOR.MINOR.PATCH",
        )
        for key, record in manifest.components.items()
        if parse_version(record.version) is None
    ]


def _budget_findings(manifest: Manifest, budget: int) -> list[Finding]:
    """Keep default tool definitions within the model-visible token budget.

    Args:
        manifest (Manifest): Current server manifest.
        budget (int): Maximum estimated tokens.

    Returns:
        list[Finding]: A finding when the default tools exceed the budget.
    """
    tokens = manifest.totals.default_tool_model_tokens
    if tokens <= budget:
        return []
    message = f"default tool definitions use about {tokens:,} model-visible tokens, over the {budget:,} budget; shorten descriptions or schemas"
    return [Finding("budget", "tools", message)]


def _server_findings(lock: Manifest, current: Manifest) -> list[Finding]:
    """Report changes to the server's identity or instructions.

    Args:
        lock (Manifest): Recorded manifest.
        current (Manifest): Current manifest.

    Returns:
        list[Finding]: A finding naming the changed fields.
    """
    old, new = lock.server.model_dump(), current.server.model_dump()
    # The package version changes with every release and is recorded for information only;
    # component versions are what the lock governs.
    changed = [name for name in old if name != "version" and old[name] != new[name]]
    if not changed:
        return []
    return [Finding("server", "server", f"{", ".join(changed)} changed; record with --update")]


def _integrity_findings(lock: Manifest) -> list[Finding]:
    """Detect lock entries whose hash does not match their recorded definition.

    Args:
        lock (Manifest): Recorded manifest.

    Returns:
        list[Finding]: One finding per edited entry.
    """
    message = (
        "recorded sha256 does not match the recorded definition; regenerate the lock with --update"
    )
    return [
        Finding("integrity", key, message)
        for key, record in lock.components.items()
        if sha256(record.definition) != record.sha256
    ]


def _grouped(manifest: Manifest) -> dict[str, Versions]:
    """Group component keys by kind and identifier.

    Args:
        manifest (Manifest): Manifest to group.

    Returns:
        dict[str, Versions]: ``kind:name`` to records by version (``""`` when missing).
    """
    groups: dict[str, Versions] = {}
    for key, record in manifest.components.items():
        groups.setdefault(f"{record.kind}:{record.name}", {})[record.version or ""] = (key, record)
    return groups


def _base(version: str, recorded: Versions) -> ComponentRecord | None:
    """Find the recorded version a new version replaces: the highest one below it.

    Args:
        version (str): New version.
        recorded (Versions): Recorded versions of the same component.

    Returns:
        ComponentRecord | None: Predecessor, or None when no recorded version is lower.
    """
    target = parse_version(version)
    lower = [
        (parsed, record)
        for old, (_, record) in recorded.items()
        if (parsed := parse_version(old)) is not None and target is not None and parsed < target
    ]
    return max(lower, key=lambda item: item[0])[1] if lower else None


def _changed(key: str, previous: ComponentRecord, record: ComponentRecord) -> Finding:
    """Explain a definition that changed under a recorded version.

    Args:
        key (str): Component key.
        previous (ComponentRecord): Recorded definition.
        record (ComponentRecord): Current definition.

    Returns:
        Finding: ``changed`` finding with the smallest acceptable version.
    """
    changes = diff_definition(previous.definition, record.definition)
    level = max(required_level(changes), Level.PATCH)
    facets = sorted(
        name
        for name in previous.facets.keys() | record.facets.keys()
        if previous.facets.get(name) != record.facets.get(name)
    )
    target = next_version(record.version or "", level)
    message = f"definition changed without a version bump ({", ".join(facets)}); bump version= to {target} or higher ({_summary(changes, level)})"
    return Finding("changed", key, message, tuple(changes))


def _new_version(key: str, record: ComponentRecord, recorded: Versions) -> Finding:
    """Check that a new version is at least the bump its changes need.

    Args:
        key (str): Component key.
        record (ComponentRecord): New version.
        recorded (Versions): Recorded versions of the same component.

    Returns:
        Finding: ``new-version`` when the bump suffices, ``bump`` otherwise.
    """
    version = record.version or ""
    comparable = sorted(old for old in recorded if parse_version(old) is not None)
    if parse_version(version) is None or not comparable:
        return Finding("new-version", key, "new version not recorded in the lock")
    base = _base(version, recorded)
    if base is None or base.version is None:
        message = f"version must be higher than the recorded {", ".join(comparable)}"
        return Finding("bump", key, message)
    changes = diff_definition(base.definition, record.definition)
    need, got = required_level(changes), bump_level(base.version, version)
    if got is not None and got >= need:
        detail = f"{need.name} change" if need else "no definition change"
        message = f"new version of {base.version} ({detail}) not recorded in the lock"
        return Finding("new-version", key, message, tuple(changes))
    message = f'{got.name if got else "no"} bump from {base.version} is smaller than the change requires ({_summary(changes, need)}); use version="{next_version(base.version, need)}" or higher'
    return Finding("bump", key, message, tuple(changes))


def _compare(old: Versions, new: Versions) -> list[Finding]:
    """Compare the recorded and current versions of one component.

    Args:
        old (Versions): Recorded versions.
        new (Versions): Current versions.

    Returns:
        list[Finding]: Changed, new, and removed versions.
    """
    findings: list[Finding] = []
    replaced: set[str] = set()
    for version, (key, record) in sorted(new.items()):
        if version in old:
            if old[version][1].sha256 != record.sha256:
                findings.append(_changed(key, old[version][1], record))
            continue
        findings.append(_new_version(key, record, old))
        base = _base(version, old)
        # A version below every recorded one replaces them all; it is reported as a bump.
        replaced |= {base.version or ""} if base is not None else old.keys() - new.keys()
    findings += [
        Finding(
            "removed",
            key,
            "version removed (breaking for clients that pin it); record it with --update",
        )
        for version, (key, _) in sorted(old.items())
        if version not in new and version not in replaced
    ]
    return findings


def _component_findings(
    lock: Mapping[str, Versions], current: Mapping[str, Versions]
) -> list[Finding]:
    """Compare components by identity across both manifests.

    Args:
        lock (Mapping[str, Versions]): Recorded components by identity.
        current (Mapping[str, Versions]): Current components by identity.

    Returns:
        list[Finding]: Findings in identity order.
    """
    findings: list[Finding] = []
    for identity in sorted(lock.keys() | current.keys()):
        old, new = lock.get(identity, {}), current.get(identity, {})
        if not new:
            message = "component removed (breaking for clients); record it with --update"
            findings += [Finding("removed", key, message) for key, _ in old.values()]
        elif not old:
            message = "new component not recorded in the lock"
            findings += [Finding("added", key, message) for key, _ in new.values()]
        else:
            findings += _compare(old, new)
    return findings


def review(lock: Manifest | None, current: Manifest, *, budget: int) -> list[Finding]:
    """Compare a recorded lock with the current server.

    Without a lock every component is reported as added; the caller adds a ``missing`` or
    ``unreadable`` finding saying why, which keeps an update from recording them unreviewed.

    Args:
        lock (Manifest | None): Recorded manifest, or None when there is no usable lock.
        current (Manifest): Manifest of the current server.
        budget (int): Maximum model-visible tokens of the default tools.

    Returns:
        list[Finding]: Every rule violation and unrecorded difference.
    """
    findings = _version_findings(current) + _budget_findings(current, budget)
    recorded = {} if lock is None else _grouped(lock)
    if lock is not None:
        findings += _integrity_findings(lock) + _server_findings(lock, current)
    return findings + _component_findings(recorded, _grouped(current))
