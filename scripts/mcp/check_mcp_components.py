"""Check MCP component versions, fingerprints, and token budgets against the component lock.

From the repository root:

    uv run --no-sync python scripts/mcp/check_mcp_components.py             # check (CI and hooks)
    uv run --no-sync python scripts/mcp/check_mcp_components.py --update    # record changes
    uv run --no-sync python scripts/mcp/check_mcp_components.py --update --accept-changes

--accept-changes also records reviewed changes the rules refuse, and is required to write the
first lock or to replace a missing or unreadable one: without a lock to compare with, --update
cannot tell reviewed changes from unreviewed ones.

The lock records every component of opendart_mcp.server.create_server with optional
components enabled; those that only the off-by-default service-tools setting registers are
marked optional. The server's lifespan never runs, so no network access or API key is needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from opendart_mcp.manifest import (
    Finding,
    Manifest,
    blocking,
    build_manifest,
    mark_optional,
    render_lock,
    review,
)
from opendart_mcp.settings import Settings, ToolSettings
from opendart_mcp.versioning.model import LOCK_FORMAT
from opendart_mcp.versioning.policy import FATAL

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from fastmcp import FastMCP

    type Factory = Callable[[Settings], FastMCP[Any]]

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "packages/mcp/components.lock.json"
TOOL_TOKEN_BUDGET = 10_000
UPDATE = "uv run --no-sync python scripts/mcp/check_mcp_components.py --update"
ACCEPT = "`just mcp lock --accept-changes` (" + UPDATE + " --accept-changes)"
HINTS = {
    "invalid-version": 'Declare version="MAJOR.MINOR.PATCH" on every component.',
    "budget": "Shorten tool descriptions or input schemas; `--tokens` lists each tool.",
    "changed": "Bump version= on the changed components, then run " + UPDATE + ".",
    "bump": "Use the suggested versions; after review, "
    + UPDATE
    + " --accept-changes records them.",
    "missing": "Without a lock, --update cannot tell reviewed changes from unreviewed ones, "
    + "so it writes the first lock only with --accept-changes: review every definition, then run "
    + ACCEPT
    + ".",
    "unreadable": "--update refuses unreviewed changes by comparing with the lock, so restore a "
    + "readable one first. For a merge conflict, take either side's lock whole (git checkout "
    + "--ours or --theirs -- packages/mcp/components.lock.json) and run `just mcp lock`, which "
    + "records the other side's version bumps on top of it. Replacing the lock instead records "
    + "every definition unreviewed; after reviewing them, run "
    + ACCEPT
    + ".",
}
RECORD_HINT = "Record intended changes with `just mcp lock` (" + UPDATE + ") and commit the lock."
CONFLICT_MARKER = re.compile(r"^(?:<{7}|\|{7}|={7}|>{7})(?: |$)", re.MULTILINE)


def default_settings(*, optional: bool) -> Settings:
    """Build default settings that ignore the environment.

    Args:
        optional: Register the off-by-default escape-hatch tools.

    Returns:
        Settings with every group at its defaults.
    """
    groups = {
        name: field.get_default(call_default_factory=True)
        for name, field in Settings.model_fields.items()
    }
    groups["tools"] = ToolSettings(enable_service_tools=optional)
    return Settings(**groups)


def create_server(settings: Settings) -> FastMCP[Any]:
    """Build the OpenDART server without entering its lifespan.

    Args:
        settings: Server configuration.

    Returns:
        The server.
    """
    from opendart_mcp.server import create_server as create

    return create(settings)


async def current_manifest(factory: Factory) -> Manifest:
    """Fingerprint every component, marking those the default configuration omits.

    Args:
        factory: Builds a server from settings.

    Returns:
        Manifest of the full configuration.
    """
    full = await build_manifest(factory(default_settings(optional=True)))
    default = await build_manifest(factory(default_settings(optional=False)))
    return mark_optional(full, default)


def unreadable(text: str, error: ValueError) -> str:
    """Explain why lock text could not be read.

    Args:
        text: Lock file contents.
        error: The JSON or validation error.

    Returns:
        A short description, naming merge-conflict markers when there are any.
    """
    if (marker := CONFLICT_MARKER.search(text)) is not None:
        line = text.count("\n", 0, marker.start()) + 1
        return f"unreadable: it contains merge-conflict markers (first at line {line})"
    if isinstance(error, json.JSONDecodeError):
        return (
            f"unreadable: invalid JSON at line {error.lineno}, column {error.colno} ({error.msg})"
        )
    return f"unreadable: not a component lock ({error.__class__.__name__})"


def load_lock(path: Path) -> tuple[Manifest | None, str | None, Finding | None]:
    """Read the lock file.

    Args:
        path: Lock location.

    Returns:
        The parsed lock, its text, and a ``missing`` or ``unreadable`` finding when it is
        unusable.
    """
    if not path.exists():
        message = "does not exist, so there is nothing to compare the server with"
        return None, None, Finding("missing", path.name, message)
    text = path.read_text(encoding="utf-8")
    try:
        lock = Manifest.model_validate(json.loads(text))
    except (ValueError, ValidationError) as error:
        return None, text, Finding("unreadable", path.name, unreadable(text, error))
    if lock.format != LOCK_FORMAT:
        message = (
            f"unreadable: it has format {lock.format}; this checker reads format {LOCK_FORMAT}"
        )
        return None, text, Finding("unreadable", path.name, message)
    return lock, text, None


def plural(count: int, noun: str) -> str:
    """Count a noun.

    Args:
        count: How many.
        noun: Singular noun.

    Returns:
        Text such as ``1 template`` or ``4 tools``.
    """
    return f"{count} {noun}{"" if count == 1 else "s"}"


def summary(manifest: Manifest) -> str:
    """Describe the components and the token budget.

    Args:
        manifest: Current manifest.

    Returns:
        One line of counts and token estimates.
    """
    counts, totals = manifest.totals.counts, manifest.totals
    optional = sum(1 for r in manifest.components.values() if r.kind == "tool" and r.optional)
    kinds = ", ".join(plural(counts[kind], kind) for kind in ("resource", "template", "prompt"))
    return (
        f"{plural(counts["tool"], "tool")} ({optional} optional), {kinds}; default tools use "
        f"~{totals.default_tool_model_tokens:,} of {TOOL_TOKEN_BUDGET:,} model-visible "
        f"tokens (~{totals.tool_model_tokens:,} with optional tools); all definitions, "
        f"including output schemas, ~{totals.definition_tokens:,} tokens"
    )


def token_table(manifest: Manifest) -> list[str]:
    """List model-visible tokens per tool, largest first.

    Args:
        manifest: Current manifest.

    Returns:
        Table lines.
    """
    tools = [r for r in manifest.components.values() if r.kind == "tool"]
    tools.sort(key=lambda record: (-record.model_tokens, record.name))
    return [f"  {r.model_tokens:>6,}  {r.name}{" (optional)" if r.optional else ""}" for r in tools]


def report(findings: Sequence[Finding], *, prefix: str) -> None:
    """Print findings with the hints that apply to them.

    Args:
        findings: Findings to print.
        prefix: Line prefix such as ``error``.
    """
    for finding in findings:
        print(f"{prefix}: {finding}", file=sys.stderr)
    codes = {finding.code for finding in findings}
    hints = [hint for code, hint in HINTS.items() if code in codes]
    if codes - HINTS.keys():
        hints.append(RECORD_HINT)
    for hint in hints:
        print(hint, file=sys.stderr)


def check(current: Manifest, lock_path: Path) -> int:
    """Compare the server with the lock without changing anything.

    Args:
        current: Current manifest.
        lock_path: Lock location.

    Returns:
        Exit status.
    """
    lock, text, problem = load_lock(lock_path)
    findings = review(lock, current, budget=TOOL_TOKEN_BUDGET)
    if problem is not None:
        findings = [*(f for f in findings if f.code in FATAL), problem]
    elif not findings and render_lock(current) != text:
        message = "not in canonical form, or its derived fields are stale"
        findings = [Finding("stale", lock_path.name, message)]
    if findings:
        report(findings, prefix="error")
        return 1
    print(f"MCP component lock OK: {len(current.components)} components match {lock_path.name}")
    return 0


def update(current: Manifest, lock_path: Path, *, accept: bool) -> int:
    """Rewrite the lock after intended changes, refusing unreviewed ones.

    A missing or unreadable lock leaves nothing to compare with, so every component would be
    recorded as new; that takes ``accept`` too.

    Args:
        current: Current manifest.
        lock_path: Lock location.
        accept: Also record changes under recorded versions and short version bumps, and
            replace a missing or unreadable lock.

    Returns:
        Exit status.
    """
    lock, text, problem = load_lock(lock_path)
    findings = review(lock, current, budget=TOOL_TOKEN_BUDGET)
    refused = blocking([*findings, *filter(None, [problem])], update=True, accept=accept)
    if refused:
        report(refused, prefix="error")
        print("The lock was not changed.", file=sys.stderr)
        return 1
    if problem is not None:
        print(
            f"warning: {problem}; writing a new lock from the current definitions", file=sys.stderr
        )
    rendered = render_lock(current)
    if rendered == text:
        print(f"{lock_path.name} is up to date")
        return 0
    for finding in findings:
        print(f"recorded ({finding.code}): {finding.key}")
    lock_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {lock_path.name} ({len(current.components)} components)")
    return 0


def run(
    *, lock_path: Path, write: bool, accept: bool, tokens: bool, factory: Factory = create_server
) -> int:
    """Build the current manifest and check or update the lock.

    Args:
        lock_path: Lock location.
        write: Rewrite the lock instead of checking it.
        accept: With ``write``, record reviewed changes the rules would refuse.
        tokens: Also list model-visible tokens per tool.
        factory: Builds a server from settings; tests pass small servers.

    Returns:
        Exit status.
    """
    current = asyncio.run(current_manifest(factory))
    print(f"MCP components: {summary(current)}", flush=True)
    if tokens:
        print("\n".join(token_table(current)), flush=True)
    if write:
        return update(current, lock_path, accept=accept)
    return check(current, lock_path)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the check.

    Args:
        argv: Arguments; None reads the command line.

    Returns:
        Exit status.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--lock", type=Path, default=LOCK, help="lock file (default: %(default)s)")
    parser.add_argument("--update", action="store_true", help="rewrite the lock")
    parser.add_argument(
        "--accept-changes",
        action="store_true",
        help="with --update, also record reviewed changes under recorded versions and short "
        + "bumps, and write the first lock or replace a missing or unreadable one",
    )
    parser.add_argument("--tokens", action="store_true", help="list model-visible tokens per tool")
    args = parser.parse_args(argv)
    if args.accept_changes and not args.update:
        parser.error("--accept-changes requires --update")
    return run(
        lock_path=args.lock, write=args.update, accept=args.accept_changes, tokens=args.tokens
    )


if __name__ == "__main__":
    sys.exit(main())
