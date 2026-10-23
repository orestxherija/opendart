"""Classify the differences between two versions of a component definition.

Schemas are compared by ``schema.diff_schema``. Elsewhere, a changed MIME type, a removed or
newly required prompt argument, and a tool that starts requiring background tasks are
MAJOR; descriptions, titles, annotations, icons, and ``_meta`` are PATCH; anything else is
MINOR. ``_meta.fastmcp.version`` is ignored: it is the version itself.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from opendart_mcp.versioning.levels import ABSENT, Change, Level, show
from opendart_mcp.versioning.schema import diff_schema

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

SEMVER: Final = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
DESCRIPTIVE: Final = frozenset({"title", "description", "annotations", "icons", "name", "size"})


def parse_version(version: str | None) -> tuple[int, int, int] | None:
    """Parse a ``MAJOR.MINOR.PATCH`` version.

    Args:
        version (str | None): Declared version.

    Returns:
        tuple[int, int, int] | None: Numbers, or None when missing or malformed.
    """
    match = SEMVER.fullmatch(version or "")
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def bump_level(old: str, new: str) -> Level | None:
    """Classify a version increase.

    Args:
        old (str): Previous version.
        new (str): Current version.

    Returns:
        Level | None: Size of the bump, or None unless both parse and ``new`` is higher.
    """
    before, after = parse_version(old), parse_version(new)
    if before is None or after is None or after <= before:
        return None
    if after[0] != before[0]:
        return Level.MAJOR
    return Level.MINOR if after[1] != before[1] else Level.PATCH


def next_version(version: str, level: Level) -> str:
    """Suggest the smallest version that makes a bump of the given size.

    Args:
        version (str): Current version; must parse.
        level (Level): Required bump.

    Returns:
        str: Suggested version, or ``version`` itself when nothing is required.
    """
    parsed = parse_version(version)
    if parsed is None or level is Level.NONE:
        return version
    major, minor, patch = parsed
    if level is Level.MAJOR:
        return f"{major + 1}.0.0"
    return f"{major}.{minor + 1}.0" if level is Level.MINOR else f"{major}.{minor}.{patch + 1}"


def _meta(value: object) -> object:
    """Drop the declared version from ``_meta``, which changes with every bump.

    Args:
        value (object): ``_meta`` object, or the absent marker.

    Returns:
        object: ``_meta`` without ``fastmcp.version`` and ``fastmcp.versions``.
    """
    if not isinstance(value, dict):
        return value
    fastmcp = value.get("fastmcp")
    if not isinstance(fastmcp, dict):
        return value
    rest = {k: v for k, v in fastmcp.items() if k not in {"version", "versions"}}
    return {**value, "fastmcp": rest}


def _input(old: object, new: object) -> list[Change]:
    """Compare input schemas.

    Args:
        old (object): Previous schema.
        new (object): Current schema.

    Returns:
        list[Change]: Classified changes.
    """
    return diff_schema(old, new, mode="input", path="inputSchema")


def _output(old: object, new: object) -> list[Change]:
    """Compare output schemas; adding one is MINOR and removing one MAJOR.

    Args:
        old (object): Previous schema, or the absent marker.
        new (object): Current schema, or the absent marker.

    Returns:
        list[Change]: Classified changes.
    """
    if old is ABSENT or new is ABSENT:
        added = old is ABSENT
        detail = "output schema added" if added else "output schema removed"
        return [Change(Level.MINOR if added else Level.MAJOR, "outputSchema", detail)]
    return diff_schema(old, new, mode="output", path="outputSchema")


def _task_support(value: object) -> object:
    """Read a tool's task support; absent means forbidden.

    Args:
        value (object): ``execution`` object, or the absent marker.

    Returns:
        object: ``forbidden``, ``optional``, or ``required``.
    """
    return value.get("taskSupport", "forbidden") if isinstance(value, dict) else "forbidden"


def _execution(old: object, new: object) -> list[Change]:
    """Compare execution settings; requiring background tasks excludes clients.

    Args:
        old (object): Previous ``execution``, or the absent marker.
        new (object): Current ``execution``, or the absent marker.

    Returns:
        list[Change]: Classified change.
    """
    before, after = _task_support(old), _task_support(new)
    level = Level.MAJOR if after == "required" != before else Level.MINOR
    return [Change(level, "execution", f"taskSupport {show(before)} -> {show(after)}")]


def _arguments_by_name(value: object) -> dict[str, Mapping[str, object]]:
    """Index prompt arguments by name.

    Args:
        value (object): ``arguments`` list, or the absent marker.

    Returns:
        dict[str, Mapping[str, object]]: Arguments by name.
    """
    if not isinstance(value, list):
        return {}
    return {str(item.get("name")): item for item in value if isinstance(item, dict)}


def _arguments(old: object, new: object) -> list[Change]:
    """Compare prompt arguments.

    Args:
        old (object): Previous ``arguments``, or the absent marker.
        new (object): Current ``arguments``, or the absent marker.

    Returns:
        list[Change]: Classified changes.
    """
    before, after = _arguments_by_name(old), _arguments_by_name(new)
    changes = [
        Change(Level.MAJOR, f"arguments.{name}", "argument removed")
        for name in sorted(before.keys() - after.keys())
    ]
    for name in sorted(after.keys() - before.keys()):
        required = after[name].get("required") is True
        level = Level.MAJOR if required else Level.MINOR
        detail = f"{"required" if required else "optional"} argument added"
        changes.append(Change(level, f"arguments.{name}", detail))
    for name in sorted(before.keys() & after.keys()):
        changes += _argument(name, before[name], after[name])
    if not changes:
        changes.append(Change(Level.PATCH, "arguments", "argument order changed"))
    return changes


def _argument(name: str, old: Mapping[str, object], new: Mapping[str, object]) -> list[Change]:
    """Compare one prompt argument.

    Args:
        name (str): Argument name.
        old (Mapping[str, object]): Previous argument.
        new (Mapping[str, object]): Current argument.

    Returns:
        list[Change]: Classified changes.
    """
    was, now = old.get("required") is True, new.get("required") is True
    changes = []
    if was != now:
        level = Level.MAJOR if now else Level.MINOR
        changes.append(Change(level, f"arguments.{name}", "now required" if now else "optional"))
    if {k: v for k, v in old.items() if k != "required"} != {
        k: v for k, v in new.items() if k != "required"
    }:
        changes.append(Change(Level.PATCH, f"arguments.{name}", "details changed"))
    return changes


def _mime_type(old: object, new: object) -> list[Change]:
    """Compare resource MIME types; consumers parse content by type.

    Args:
        old (object): Previous MIME type, or the absent marker.
        new (object): Current MIME type, or the absent marker.

    Returns:
        list[Change]: MAJOR change.
    """
    return [Change(Level.MAJOR, "mimeType", f"{show(old)} -> {show(new)}")]


_FACETS: Final[Mapping[str, Callable[[object, object], list[Change]]]] = {
    "inputSchema": _input,
    "outputSchema": _output,
    "execution": _execution,
    "arguments": _arguments,
    "mimeType": _mime_type,
}


def _facet(key: str, old: object, new: object) -> list[Change]:
    """Classify a change to one top-level part of a definition.

    Args:
        key (str): Top-level key.
        old (object): Previous value, or the absent marker.
        new (object): Current value, or the absent marker.

    Returns:
        list[Change]: Classified changes.
    """
    if key in _FACETS:
        return _FACETS[key](old, new)
    if key in DESCRIPTIVE or key == "_meta":
        detail = "changed" if key == "description" else f"{show(old)} -> {show(new)}"
        return [Change(Level.PATCH, key, detail)]
    return [Change(Level.MINOR, key, f"{show(old)} -> {show(new)}")]


def diff_definition(old: Mapping[str, object], new: Mapping[str, object]) -> list[Change]:
    """Classify every difference between two definitions of one component.

    Args:
        old (Mapping[str, object]): Previous definition.
        new (Mapping[str, object]): Current definition.

    Returns:
        list[Change]: Classified changes; empty when only the version differs.
    """
    changes: list[Change] = []
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key, ABSENT), new.get(key, ABSENT)
        if key == "_meta":
            before, after = _meta(before), _meta(after)
        if before != after:
            changes += _facet(key, before, after)
    return changes
