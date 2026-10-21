# Optional HTTP checks

`check_http.py` needs Python 3.11+ and only the standard library. Run it against
application files without installing httpx2 or running application code:

```sh
python3 "/path/to/plugin/scripts/check_http.py" --root . src --format json
```

| Code | Explicit construct detected |
|---|---|
| `HTTP001` | `verify=False` on a directly identified httpx2 call |
| `HTTP002` | `timeout=None` on a directly identified httpx2 call |
| `HTTP003` | A direct httpx2 client constructor executing at import time |

The checker follows import aliases and simple local client bindings. It does
not infer wrappers, settings values, intermodule flows, or every Python binding
pattern. Findings need context: an explicit outer deadline can justify a
disabled per-phase timeout. The checker is advisory, not a security proof or
automatic migration tool.

Tests, virtual environments, and build output are excluded by default.
`--include-tests` removes default exclusions. `--exclude 'generated/**'` adds
project-relative glob exclusions. Repeat `--check HTTP001` to select codes.
JSON output has `version`, `findings`, and `errors`; each finding includes code,
relative path, line, column, and message. Exit codes: 0 clean, 1 findings,
2 input/parse errors. The command reads files and never rewrites them.

The bundled hook is off by default. Copy
[config.example.toml](../hooks/config.example.toml) to the consuming project's
`.claude/python-http.toml` to enable it. `enabled = false` disables it again.
The hook reads the project root from `CLAUDE_PROJECT_DIR`, falling back to the
event's working directory. It checks only Python files modified through
`Edit`, `Write`, or `MultiEdit`; shell-created changes need an explicit CLI run.
The configured Python interpreter must be available as `python3`.

The hook always returns success and provides structured `PostToolUse` feedback
after the edit. It cannot prevent or undo that edit. It does not launch models,
read transcripts, invoke tests, or claim validation based on conversation text.
Hosts without hooks can use the skill instructions and command directly.
