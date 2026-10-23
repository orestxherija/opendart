#!/usr/bin/env python3
"""Select the CI checks that a pull request, a push to main, or a manual run needs.

In GitHub Actions the event payload sets the policy and Git lists the changed files; the
selection goes to GITHUB_OUTPUT as JSON, with the unselected jobs that the gate may skip.
Locally, preview a branch with ``just ci plan`` or pass --base, --head, and --event.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
FILTERS = ROOT / ".github" / "ci-paths.toml"
EVENTS = ("pull_request", "push", "workflow_dispatch")
# Reusable-workflow jobs in ci.yml; the gate lets exactly the unselected ones skip.
JOBS = ("quality", "release", "sdk", "mcp", "image", "reference")
# Manual-run inputs in ci.yml and their defaults.
INPUTS = {
    "quality": True,
    "audit": True,
    "release": True,
    "distributions": True,
    "sdk": True,
    "mcp": True,
    "image": True,
    "reference": True,
    "contracts": False,
}

type Filters = dict[str, tuple[str, ...]]


@dataclass(frozen=True, kw_only=True)
class Event:
    """The parts of a GitHub event that decide which checks run."""

    name: str
    ref: str = ""
    default_branch: str = "main"
    draft: bool = False
    base: str = ""
    head: str = "HEAD"
    inputs: Mapping[str, bool] = field(default_factory=dict)

    @property
    def on_default_branch(self) -> bool:
        return self.ref == f"refs/heads/{self.default_branch}"


def load_filters(path: Path = FILTERS) -> Filters:
    """Read each filter's ordered patterns, with included filters' patterns first."""
    tables = tomllib.loads(path.read_text())

    def expand(name: str, seen: frozenset[str]) -> list[str]:
        if name in seen:
            msg = f"Filter {name} includes itself"
            raise ValueError(msg)
        table = tables[name]
        patterns = [
            pattern
            for included in table.get("include", [])
            for pattern in expand(included, seen | {name})
        ]
        return [*patterns, *table["paths"]]

    return {name: tuple(expand(name, frozenset())) for name in tables}


def matches(path: str, patterns: Iterable[str]) -> bool:
    """Report whether the last pattern that matches a path is an inclusion."""
    candidate = PurePosixPath(path)
    selected = False
    for pattern in patterns:
        if candidate.full_match(pattern.removeprefix("!")):
            selected = not pattern.startswith("!")
    return selected


def git_lines(*arguments: str, cwd: Path) -> list[str] | None:
    result = subprocess.run(
        ["git", *arguments], capture_output=True, check=False, cwd=cwd, text=True
    )
    if result.returncode:
        print(
            f"::warning::git {" ".join(arguments)} failed; selecting every check. {result.stderr.strip()}"
        )
        return None
    return [line for line in result.stdout.splitlines() if line]


def changed_files(base: str, head: str, cwd: Path = ROOT) -> list[str] | None:
    """List files changed from base's merge base to head, or None when unknown.

    An empty head compares the working tree, including untracked files.
    """
    if not base or set(base) == {"0"}:
        return None
    if head:
        return git_lines("diff", "--name-only", "--no-renames", f"{base}...{head}", "--", cwd=cwd)
    tracked = git_lines("diff", "--name-only", "--no-renames", "--merge-base", base, "--", cwd=cwd)
    untracked = git_lines("ls-files", "--others", "--exclude-standard", cwd=cwd)
    if tracked is None or untracked is None:
        return None
    return sorted({*tracked, *untracked})


def select(event: Event, changed: list[str] | None, filters: Filters) -> dict[str, bool]:
    """Apply the event policy to the filters that the changed files select."""
    if event.name == "workflow_dispatch":
        chosen = {name: event.inputs.get(name, default) for name, default in INPUTS.items()}
        selection = {
            "style": chosen["quality"],
            "audit": chosen["audit"],
            "release": chosen["release"] or chosen["distributions"],
            "distributions": chosen["distributions"],
            "sdk": chosen["sdk"],
            "mcp": chosen["mcp"],
            "conformance": chosen["mcp"],
            "image": chosen["image"],
            "base_images": chosen["image"],
            "vulnerabilities": chosen["image"],
            "reference": chosen["reference"],
            "publish": False,
            "contracts": chosen["contracts"] and event.on_default_branch,
        }
    else:
        hit = {
            name: changed is None or any(matches(path, patterns) for path in changed)
            for name, patterns in filters.items()
        }
        pull_request = event.name == "pull_request"
        ready = pull_request and not event.draft
        push_to_main = event.name == "push" and event.on_default_branch
        distributions = ready and hit["distributions"]
        image = ready and hit["image"]
        selection = {
            "style": pull_request,
            "audit": pull_request and hit["audit"],
            "release": pull_request and (hit["release"] or distributions),
            "distributions": distributions,
            "sdk": hit["sdk"],
            "mcp": hit["mcp"],
            "conformance": hit["mcp"] and not event.draft,
            "image": image,
            "base_images": image and hit["base_images"],
            "vulnerabilities": image and hit["vulnerabilities"],
            "reference": hit["reference"],
            "publish": push_to_main and (hit["image"] or hit["publisher"]),
            "contracts": push_to_main and hit["api"],
        }
    selection["quality"] = selection["style"] or selection["audit"]
    return selection


def skippable(selection: Mapping[str, bool]) -> str:
    """Name the reusable-workflow jobs that the gate may find skipped."""
    return ",".join(job for job in JOBS if not selection[job])


def as_bool(value: object) -> bool:
    return value is True or str(value).lower() == "true"


def event_from_environment(environ: Mapping[str, str]) -> Event:
    """Read the current GitHub Actions event."""
    name = environ["GITHUB_EVENT_NAME"]
    if name not in EVENTS:
        msg = f"Unsupported event: {name}"
        raise SystemExit(msg)
    payload = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text())
    pull_request = payload.get("pull_request") or {}
    if name == "pull_request":
        base, head = pull_request["base"]["sha"], pull_request["head"]["sha"]
    else:
        base, head = payload.get("before", ""), environ.get("GITHUB_SHA", "HEAD")
    return Event(
        name=name,
        ref=environ.get("GITHUB_REF", ""),
        default_branch=payload.get("repository", {}).get("default_branch", "main"),
        draft=bool(pull_request.get("draft")),
        base=base,
        head=head,
        inputs={key: as_bool(value) for key, value in (payload.get("inputs") or {}).items()},
    )


def write_outputs(
    selection: Mapping[str, bool], changed: list[str] | None, environ: Mapping[str, str]
) -> None:
    """Record the selection for later jobs and summarize it for the run page."""
    with Path(environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"selection={json.dumps(selection, sort_keys=True)}\n")
        output.write(f"skippable={skippable(selection)}\n")
    if summary_path := environ.get("GITHUB_STEP_SUMMARY"):
        files = "every file (no comparison)" if changed is None else f"{len(changed)} changed files"
        rows = "\n".join(
            f"| {name} | {"yes" if chosen else "no"} |"
            for name, chosen in sorted(selection.items())
        )
        with Path(summary_path).open("a") as summary:
            summary.write(f"Selected from {files}.\n\n| Check | Runs |\n| --- | --- |\n{rows}\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--event", choices=EVENTS, help="preview this event instead of reading GitHub's"
    )
    parser.add_argument("--base", default="origin/main", help="revision to compare against")
    parser.add_argument(
        "--head", default="HEAD", help="revision to compare; empty for the working tree"
    )
    parser.add_argument("--draft", action="store_true", help="preview a draft pull request")
    args = parser.parse_args(argv)

    filters = load_filters()
    if args.event is None and "GITHUB_EVENT_PATH" in os.environ:
        event = event_from_environment(os.environ)
        changed = (
            None if event.name == "workflow_dispatch" else changed_files(event.base, event.head)
        )
        selection = select(event, changed, filters)
        write_outputs(selection, changed, os.environ)
    else:
        name = args.event or "pull_request"
        event = Event(
            name=name, ref="refs/heads/main", draft=args.draft, base=args.base, head=args.head
        )
        changed = None if name == "workflow_dispatch" else changed_files(event.base, event.head)
        selection = select(event, changed, filters)
    print(
        json.dumps(
            {"selection": selection, "skippable": skippable(selection)}, indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
