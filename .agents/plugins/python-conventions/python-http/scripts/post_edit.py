#!/usr/bin/env python3
"""Optional, advisory PostToolUse adapter for check_http.py (Python 3.11+)."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

# Sibling import works from any plugin installation directory, including spaces.
from check_http import CHECKS, DEFAULT_EXCLUDES, scan_paths


def feedback(message: str) -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }


def handle(event: object) -> dict[str, object]:
    if not isinstance(event, dict) or event.get("hook_event_name") != "PostToolUse":
        return {}
    if event.get("tool_name") not in {"Edit", "Write", "MultiEdit"}:
        return {}
    tool_input = event.get("tool_input", {})
    filename = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(filename, str) or not filename.endswith(".py"):
        return {}
    cwd = event.get("cwd")
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    if not isinstance(project, str):
        return {}
    root = Path(project).resolve()
    config_path = root / ".claude" / "python-http.toml"
    if not config_path.is_file():
        return {}
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8")).get(
            "python-http", {}
        )
        if not isinstance(config, dict):
            raise ValueError("[python-http] must be a table")
        if config.get("enabled", False) is not True:
            return {}
        exclusions = config.get("exclude", [])
        checks = config.get("checks", list(CHECKS))
        if not isinstance(exclusions, list) or not all(
            isinstance(value, str) for value in exclusions
        ):
            raise ValueError("exclude must be an array of glob strings")
        if not isinstance(checks, list) or not all(value in CHECKS for value in checks):
            raise ValueError("checks must contain only HTTP001, HTTP002, HTTP003")
        path = Path(filename)
        if not path.is_absolute():
            path = Path(cwd if isinstance(cwd, str) else project) / path
        if not path.resolve().is_relative_to(root):
            return {}
        findings, errors = scan_paths(
            [path], root=root, excludes=(*DEFAULT_EXCLUDES, *exclusions), checks=checks
        )
    except (OSError, ValueError, TypeError) as exc:
        return feedback(f"python-http advisory checker could not run: {exc}")
    if not findings and not errors:
        return {}
    lines = ["python-http advisory findings (the edit already completed):"]
    lines.extend(f"{f.path}:{f.line}: {f.code} {f.message}" for f in findings[:10])
    if len(findings) > 10:
        lines.append(
            f"{len(findings) - 10} further findings; run check_http.py for all."
        )
    lines.extend(f"{error['path']}: {error['message']}" for error in errors)
    return feedback("\n".join(lines))


def main() -> None:
    try:
        result = handle(json.load(sys.stdin))
    except (ValueError, TypeError):
        result = {}
    except Exception as exc:
        # This adapter is advisory even when input or an unexpected checker
        # failure falls outside the narrower errors handled by scan_paths.
        result = feedback(
            f"python-http advisory checker could not run ({type(exc).__name__}): {exc}"
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
