"""scripts/mcp/check_mcp_components.py: check and update the lock against small servers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def script():
    path = ROOT / "scripts/mcp/check_mcp_components.py"
    spec = importlib.util.spec_from_file_location("check_mcp_components", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def by_query(query: str) -> str:
    return query


async def by_code(code: str) -> str:
    return code


async def extra_tool() -> str:
    return "extra"


def brief(company: str) -> str:
    return company


def factory(
    *, description="Find widgets.", version="1.0.0", fn=by_query, prompt=True, instructions="Fake."
):
    def build(settings):
        server = FastMCP("Fake", version="0.0.1", instructions=instructions)
        server.tool(name="find", version=version, description=description)(fn)
        if settings.tools.enable_service_tools:
            server.tool(name="extra", version="1.0.0", description="Optional.")(extra_tool)
        if prompt:
            server.prompt(name="brief", version="1.0.0", description="Brief.")(brief)
        return server

    return build


@pytest.fixture
def lock(tmp_path):
    return tmp_path / "components.lock.json"


@pytest.fixture
def run(script, lock):
    def run(*, write=False, accept=False, tokens=False, **spec):
        return script.run(
            lock_path=lock, write=write, accept=accept, tokens=tokens, factory=factory(**spec)
        )

    return run


def conflicted(text):
    lines = text.splitlines(keepends=True)
    middle = len(lines) // 2
    ours, theirs = lines[middle], lines[middle].replace('"', "'")
    markers = ["<<<<<<< HEAD\n", ours, "=======\n", theirs, ">>>>>>> main\n"]
    return "".join([*lines[:middle], *markers, *lines[middle + 1 :]]), middle + 1


def test_a_missing_lock_fails_the_check(run, capsys):
    assert run() == 1
    err = capsys.readouterr().err
    assert "error: components.lock.json: does not exist" in err
    assert "just mcp lock --accept-changes" in err
    assert "Record intended changes with `just mcp lock`" not in err


def test_the_first_lock_needs_accept_changes(run, lock, capsys):
    assert run(write=True) == 1
    err = capsys.readouterr().err
    assert "components.lock.json: does not exist" in err
    assert "writes the first lock only with --accept-changes" in err
    assert "The lock was not changed." in err
    assert not lock.exists()
    assert run(write=True, accept=True) == 0
    captured = capsys.readouterr()
    assert "writing a new lock from the current definitions" in captured.err
    assert "recorded (added): tool:find@1.0.0" in captured.out
    assert "Wrote components.lock.json (3 components)" in captured.out
    assert run() == 0
    assert (
        "MCP component lock OK: 3 components match components.lock.json" in capsys.readouterr().out
    )


def test_an_unbumped_change_cannot_slip_in_through_a_conflicted_lock(run, lock, capsys):
    run(write=True, accept=True)
    canonical = lock.read_text()
    text, line = conflicted(canonical)
    lock.write_text(text)
    changed = {"description": "Find other widgets."}
    for write in (False, True):
        assert run(write=write, **changed) == 1
        err = capsys.readouterr().err
        assert f"unreadable: it contains merge-conflict markers (first at line {line})" in err
        assert "take either side's lock whole" in err
        assert "Record intended changes with `just mcp lock`" not in err
    assert lock.read_text() == text
    lock.write_text(canonical)
    assert run(write=True, **changed) == 1
    assert "definition changed without a version bump" in capsys.readouterr().err
    lock.write_text(text)
    assert run(write=True, accept=True, **changed) == 0
    assert "merge-conflict markers" in capsys.readouterr().err
    assert run(**changed) == 0


def test_the_summary_reports_both_configurations(run, capsys):
    run(write=True, accept=True)
    out = capsys.readouterr().out
    assert "MCP components: 2 tools (1 optional), 0 resources, 0 templates, 1 prompt;" in out
    assert "of 10,000 model-visible tokens" in out
    assert "all definitions, including output schemas, ~" in out


def test_the_lock_marks_optional_tools(run, lock):
    run(write=True, accept=True)
    components = json.loads(lock.read_text())["components"]
    assert components["tool:extra@1.0.0"]["optional"] is True
    assert components["tool:find@1.0.0"]["optional"] is False


def test_an_update_without_changes_leaves_the_lock_alone(run, lock, capsys):
    run(write=True, accept=True)
    before = lock.read_bytes()
    assert run(write=True) == 0
    assert "components.lock.json is up to date" in capsys.readouterr().out
    assert lock.read_bytes() == before


def test_a_change_without_a_bump_needs_review(run, lock, capsys):
    run(write=True, accept=True)
    before = lock.read_bytes()
    assert run(description="Find other widgets.") == 1
    err = capsys.readouterr().err
    assert "tool:find@1.0.0: definition changed without a version bump (description)" in err
    assert "bump version= to 1.0.1 or higher" in err
    assert run(write=True, description="Find other widgets.") == 1
    assert "The lock was not changed." in capsys.readouterr().err
    assert lock.read_bytes() == before
    assert run(write=True, accept=True, description="Find other widgets.") == 0
    assert run(description="Find other widgets.") == 0


def test_a_bump_is_recorded_by_update(run, capsys):
    run(write=True, accept=True)
    assert run(version="1.0.1", description="Find other widgets.") == 1
    assert "new version of 1.0.0 (PATCH change) not recorded" in capsys.readouterr().err
    assert run(write=True, version="1.0.1", description="Find other widgets.") == 0
    assert run(version="1.0.1", description="Find other widgets.") == 0


def test_a_bump_smaller_than_the_change_is_refused_unless_accepted(run, capsys):
    run(write=True, accept=True)
    assert run(version="1.1.0", fn=by_code) == 1
    err = capsys.readouterr().err
    assert "MINOR bump from 1.0.0 is smaller than the change requires (MAJOR:" in err
    assert 'use version="2.0.0" or higher' in err
    assert run(write=True, version="1.1.0", fn=by_code) == 1
    assert run(write=True, accept=True, version="1.1.0", fn=by_code) == 0
    assert run(write=True, version="2.0.0", fn=by_code) == 0


def test_removals_and_instruction_changes_are_recorded_by_update(run, capsys):
    run(write=True, accept=True)
    assert run(prompt=False, instructions="New.") == 1
    err = capsys.readouterr().err
    assert "prompt:brief@1.0.0: component removed (breaking for clients)" in err
    assert "server: instructions_sha256, instructions_tokens changed" in err
    assert "just mcp lock" in err
    assert run(write=True, prompt=False, instructions="New.") == 0
    assert "recorded (removed): prompt:brief@1.0.0" in capsys.readouterr().out


def test_the_token_budget_cannot_be_overridden(run, script, monkeypatch, capsys):
    monkeypatch.setattr(script, "TOOL_TOKEN_BUDGET", 10)
    assert run(write=True, accept=True) == 1
    err = capsys.readouterr().err
    assert "over the 10 budget" in err
    assert "--tokens" in err


def test_invalid_versions_are_refused(run, lock, capsys):
    assert run(write=True, accept=True, version="1.0") == 1
    assert "version '1.0' is not MAJOR.MINOR.PATCH" in capsys.readouterr().err
    assert not lock.exists()
    assert run(version="1.0") == 1
    assert "is not MAJOR.MINOR.PATCH" in capsys.readouterr().err


def test_a_reformatted_lock_is_stale(run, lock, capsys):
    run(write=True, accept=True)
    canonical = lock.read_text()
    lock.write_text(json.dumps(json.loads(canonical), indent=4))
    assert run() == 1
    assert "not in canonical form" in capsys.readouterr().err
    assert run(write=True) == 0
    assert lock.read_text() == canonical


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("{", "unreadable: invalid JSON at line 1, column 2 (Expecting property name"),
        ('{"format": 1}', "unreadable: not a component lock (ValidationError)"),
    ],
)
def test_an_unreadable_lock_is_replaced_only_when_accepted(run, lock, capsys, content, problem):
    lock.write_text(content)
    assert run() == 1
    err = capsys.readouterr().err
    assert f"components.lock.json: {problem}" in err
    assert "restore a readable one first" in err
    assert run(write=True) == 1
    assert problem in capsys.readouterr().err
    assert lock.read_text() == content
    assert run(write=True, accept=True) == 0
    assert "writing a new lock" in capsys.readouterr().err
    assert run() == 0


def test_a_lock_of_another_format_is_unusable(run, lock, capsys):
    run(write=True, accept=True)
    data = json.loads(lock.read_text())
    lock.write_text(json.dumps({**data, "format": 99}))
    assert run() == 1
    assert "it has format 99; this checker reads format 1" in capsys.readouterr().err
    assert run(write=True) == 1
    assert "The lock was not changed." in capsys.readouterr().err


def test_tokens_lists_each_tool(run, capsys):
    run(write=True, accept=True, tokens=True)
    lines = capsys.readouterr().out.splitlines()
    assert any(line.strip().endswith("extra (optional)") for line in lines)
    assert any(line.strip().endswith("find") for line in lines)


def test_default_settings_ignore_the_environment(script, monkeypatch):
    monkeypatch.setenv("OPENDART_MCP_TOOLS__ENABLE_SERVICE_TOOLS", "true")
    monkeypatch.setenv("OPENDART_MCP_HTTP__RATE_LIMIT", "1")
    settings = script.default_settings(optional=False)
    assert settings.tools.enable_service_tools is False
    assert settings.http.rate_limit == 20.0
    assert script.default_settings(optional=True).tools.enable_service_tools is True


def test_accept_changes_requires_update(script, capsys):
    with pytest.raises(SystemExit) as raised:
        script.main(["--accept-changes"])
    assert raised.value.code == 2
    assert "--accept-changes requires --update" in capsys.readouterr().err


def test_main_checks_the_opendart_server(script, lock, capsys):
    assert script.main(["--lock", str(lock), "--update"]) == 1
    assert not lock.exists()
    assert script.main(["--lock", str(lock), "--update", "--accept-changes"]) == 0
    assert script.main(["--lock", str(lock)]) == 0
    out = capsys.readouterr().out
    assert "tool:find_company@1.0.0" in out
    assert "MCP component lock OK" in out
