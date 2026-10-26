"""CI runs the checks whose inputs change, under each event's policy."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci.select_components import (
    FILTERS,
    JOBS,
    ROOT,
    Event,
    changed_files,
    event_from_environment,
    load_filters,
    matches,
    select,
    skippable,
    write_outputs,
)

FILTER_SET = load_filters()
COMPONENTS = (
    "audit",
    "release",
    "distributions",
    "sdk",
    "analysis",
    "mcp",
    "image",
    "reference",
)
READY = Event(name="pull_request")
DRAFT = Event(name="pull_request", draft=True)
PUSH = Event(name="push", ref="refs/heads/main")


def selected(event: Event, *paths: str) -> set[str]:
    selection = select(event, list(paths), FILTER_SET)
    return {name for name in COMPONENTS if selection[name]}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("packages/mcp/src/opendart_mcp/server.py", {"mcp", "image", "distributions", "release"}),
        ("packages/mcp/tests/test_server.py", {"mcp"}),
        ("packages/mcp/Dockerfile", {"mcp", "image", "distributions", "release", "audit"}),
        (
            "packages/sdk/src/opendart/client.py",
            {"sdk", "mcp", "image", "distributions", "release"},
        ),
        ("packages/sdk/tests/test_client.py", {"sdk"}),
        (
            "packages/analysis/src/opendart_analysis/documents/store.py",
            {"analysis", "mcp", "image", "distributions", "release"},
        ),
        (
            "packages/analysis/pyproject.toml",
            {"analysis", "mcp", "image", "distributions", "release"},
        ),
        ("packages/analysis/README.md", {"analysis", "mcp", "distributions", "release"}),
        ("packages/analysis/tests/documents/test_store.py", {"analysis"}),
        ("scripts/testing/events.py", {"analysis", "mcp"}),
        (
            "scripts/testing/git.py",
            {"analysis", "mcp", "audit", "release", "reference"},
        ),
        ("scripts/conftest.py", {"audit", "release", "reference"}),
        (
            "packages/analysis/src/opendart_analysis/catalog/_generated.py",
            {"analysis", "mcp", "image", "distributions", "release"},
        ),
        ("packages/analysis/tests/catalog/test_generated.py", {"analysis"}),
        ("scripts/analysis/generate_mcp_registry.py", {"analysis"}),
        ("api_reference/sources/catalog.json", {"sdk", "analysis", "reference"}),
        ("importlinter.toml", {"analysis", "mcp"}),
        (".github/workflows/check-analysis.yml", {"analysis", "audit"}),
        ("scripts/sdk/generate_sdk.py", {"sdk", "analysis"}),
        ("scripts/mcp/check_mcp_conformance.py", {"mcp"}),
        ("codecov.yml", {"sdk", "analysis", "mcp"}),
        ("pyrefly.toml", {"sdk", "analysis", "mcp"}),
        ("api_reference/paths/company.yaml", {"sdk", "analysis", "reference"}),
        ("api_reference/schemas/company.yaml", {"sdk", "reference"}),
        ("api_reference/README.md", set()),
        ("scripts/api_reference/package.json", {"reference"}),
        ("scripts/api_reference/contracts/run.py", {"reference"}),
        ("scripts/api_reference/tests/test_contracts.py", {"reference"}),
        ("scripts/release/check_release.py", {"release", "distributions"}),
        ("scripts/mcp/check_mcp.py", {"mcp", "image"}),
        ("cz.toml", {"release", "distributions"}),
        ("scripts/release/tests/test_release.py", {"release"}),
        ("ruff.toml", {"sdk", "analysis", "mcp", "reference", "release"}),
        ("prek.toml", {"sdk", "analysis", "mcp", "reference", "audit"}),
        ("uv.lock", set(COMPONENTS)),
        (
            "justfile",
            {"sdk", "analysis", "mcp", "image", "reference", "release", "distributions"},
        ),
        (".github/workflows/check-sdk.yml", {"sdk", "audit"}),
        (".github/workflows/publish-mcp-image.yml", {"audit"}),
        ("scripts/ci/select_components.py", {*COMPONENTS}),
        (".github/workflows/README.md", set()),
        ("scripts/ci/tests/test_select_components.py", {"audit"}),
        ("README.md", set()),
    ],
)
def test_ready_pull_request_selects_components_whose_inputs_change(
    path: str, expected: set[str]
) -> None:
    assert selected(READY, path) == expected


def test_every_pull_request_runs_style_and_secret_checks() -> None:
    selection = select(READY, ["README.md"], FILTER_SET)
    assert selection["style"]
    assert selection["quality"]
    assert skippable(selection) == ",".join(job for job in JOBS if job != "quality")


def test_drafts_skip_expensive_checks() -> None:
    selection = select(DRAFT, ["packages/mcp/src/opendart_mcp/server.py"], FILTER_SET)
    assert selection["mcp"]
    assert not selection["image"]
    assert not selection["distributions"]
    assert not selection["release"]
    assert not selection["conformance"]


def test_image_checks_verify_bases_and_scan_only_for_their_inputs() -> None:
    source = select(READY, ["packages/mcp/src/opendart_mcp/server.py"], FILTER_SET)
    assert source["image"]
    assert not source["base_images"]
    assert not source["vulnerabilities"]
    dockerfile = select(READY, ["packages/mcp/Dockerfile"], FILTER_SET)
    assert dockerfile["base_images"]
    assert dockerfile["vulnerabilities"]


def test_push_to_main_reruns_sdk_mcp_and_reference_and_publishes() -> None:
    selection = select(PUSH, ["packages/sdk/src/opendart/client.py"], FILTER_SET)
    assert {name for name in COMPONENTS if selection[name]} == {"sdk", "mcp"}
    assert not selection["quality"]
    assert selection["publish"]
    assert not selection["contracts"]


def test_push_to_main_reruns_analysis_and_mcp_and_publishes() -> None:
    selection = select(
        PUSH, ["packages/analysis/src/opendart_analysis/documents/store.py"], FILTER_SET
    )
    assert {name for name in COMPONENTS if selection[name]} == {"analysis", "mcp"}
    assert selection["publish"]


def test_sdk_changes_never_select_analysis() -> None:
    for event in (READY, DRAFT, PUSH):
        assert not select(event, ["packages/sdk/src/opendart/client.py"], FILTER_SET)["analysis"]


def test_push_to_main_publishes_publisher_changes_and_tests_changed_contracts() -> None:
    assert select(PUSH, ["scripts/release/promote_image.sh"], FILTER_SET)["publish"]
    contract = select(PUSH, ["api_reference/paths/company.yaml"], FILTER_SET)
    assert contract["contracts"]
    assert not contract["publish"]


def test_pull_requests_never_publish_or_call_the_live_api() -> None:
    selection = select(
        READY, ["packages/mcp/Dockerfile", "api_reference/paths/company.yaml"], FILTER_SET
    )
    assert not selection["publish"]
    assert not selection["contracts"]


def test_unknown_changes_select_every_check() -> None:
    selection = select(READY, None, FILTER_SET)
    assert all(
        selection[name]
        for name in (*COMPONENTS, "style", "conformance", "base_images", "vulnerabilities")
    )
    assert skippable(selection) == ""


def test_manual_run_forces_inputs_but_never_publishes() -> None:
    selection = select(Event(name="workflow_dispatch", ref="refs/heads/feature"), None, FILTER_SET)
    assert all(selection[name] for name in COMPONENTS)
    assert not selection["publish"]
    assert not selection["contracts"]


def test_manual_full_contract_audit_runs_only_on_the_default_branch() -> None:
    inputs = {"contracts": True}
    on_main = Event(name="workflow_dispatch", ref="refs/heads/main", inputs=inputs)
    on_branch = Event(name="workflow_dispatch", ref="refs/heads/feature", inputs=inputs)
    assert select(on_main, None, FILTER_SET)["contracts"]
    assert not select(on_branch, None, FILTER_SET)["contracts"]


def test_manual_run_can_select_only_the_audit() -> None:
    inputs = dict.fromkeys(
        ("quality", "release", "distributions", "sdk", "analysis", "mcp", "image", "reference"),
        False,
    )
    selection = select(
        Event(name="workflow_dispatch", inputs={**inputs, "audit": True}), None, FILTER_SET
    )
    assert selection["quality"]
    assert not selection["style"]
    assert skippable(selection) == "release,sdk,analysis,mcp,image,reference"


@pytest.mark.parametrize(
    ("path", "patterns"),
    [
        ("a/b/c.py", ["a/**"]),
        (".github/x.yml", ["**"]),
        ("a/b.md", ["a/*.md"]),
        ("a/docs/keep.md", ["a/**", "!a/docs/**", "a/docs/keep.md"]),
    ],
)
def test_path_matches_when_its_last_matching_pattern_includes_it(
    path: str, patterns: list[str]
) -> None:
    assert matches(path, patterns)


@pytest.mark.parametrize(
    ("path", "patterns"),
    [
        ("a/b/c.md", ["a/*.md"]),
        ("a/docs/x.md", ["a/**", "!a/docs/**"]),
        ("b/c.py", ["a/**"]),
    ],
)
def test_path_does_not_match_when_excluded_or_unmatched(path: str, patterns: list[str]) -> None:
    assert not matches(path, patterns)


def test_includes_put_shared_patterns_first(tmp_path: Path) -> None:
    filters = tmp_path / "filters.toml"
    filters.write_text(
        '[base]\npaths = ["a/**"]\n\n[child]\ninclude = ["base"]\npaths = ["!a/b/**"]\n'
    )
    assert load_filters(filters)["child"] == ("a/**", "!a/b/**")


def test_include_cycles_are_rejected(tmp_path: Path) -> None:
    filters = tmp_path / "filters.toml"
    filters.write_text('[a]\ninclude = ["a"]\npaths = []\n')
    with pytest.raises(ValueError, match="includes itself"):
        load_filters(filters)


def test_every_filter_pattern_matches_a_tracked_file() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
        cwd=ROOT,
        text=True,
    )
    files = tracked.stdout.splitlines()
    stale = [
        pattern
        for patterns in FILTER_SET.values()
        for pattern in patterns
        if not pattern.startswith("!") and not any(matches(path, [pattern]) for path in files)
    ]
    assert stale == [], f"Patterns in {FILTERS.name} match no file"


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], capture_output=True, check=True, cwd=repository, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch=main")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    git(tmp_path, "config", "user.name", "CI")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "old.txt").write_text("content\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "--quiet", "--message", "base")
    return tmp_path


def test_changed_files_list_both_sides_of_a_rename(repository: Path) -> None:
    base = git(repository, "rev-parse", "HEAD")
    git(repository, "mv", "old.txt", "new.txt")
    git(repository, "commit", "--quiet", "--message", "rename")
    assert changed_files(base, "HEAD", repository) == ["new.txt", "old.txt"]


def test_changed_files_can_compare_the_working_tree(repository: Path) -> None:
    (repository / "old.txt").write_text("changed\n")
    (repository / "untracked.txt").write_text("new\n")
    assert changed_files("HEAD", "", repository) == ["old.txt", "untracked.txt"]


@pytest.mark.parametrize("base", ["", "0" * 40, "does-not-exist"])
def test_unknown_comparisons_return_none(repository: Path, base: str) -> None:
    assert changed_files(base, "HEAD", repository) is None


def test_pull_request_event_uses_the_pull_request_commits(tmp_path: Path) -> None:
    payload = tmp_path / "event.json"
    payload.write_text(
        json.dumps(
            {
                "pull_request": {
                    "base": {"sha": "b" * 40},
                    "head": {"sha": "h" * 40},
                    "draft": True,
                },
                "repository": {"default_branch": "main"},
            }
        )
    )
    event = event_from_environment(
        {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(payload),
            "GITHUB_REF": "refs/pull/1/merge",
        }
    )
    assert (event.base, event.head, event.draft) == ("b" * 40, "h" * 40, True)


def test_dispatch_event_reads_string_and_boolean_inputs(tmp_path: Path) -> None:
    payload = tmp_path / "event.json"
    payload.write_text(
        json.dumps({"inputs": {"sdk": "false", "contracts": True}, "repository": {}})
    )
    event = event_from_environment(
        {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_EVENT_PATH": str(payload),
            "GITHUB_REF": "refs/heads/main",
        }
    )
    assert event.inputs == {"sdk": False, "contracts": True}
    assert event.on_default_branch


def test_unsupported_events_fail(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Unsupported event"):
        event_from_environment(
            {"GITHUB_EVENT_NAME": "schedule", "GITHUB_EVENT_PATH": str(tmp_path / "x")}
        )


def test_outputs_record_json_selection_and_summary(tmp_path: Path) -> None:
    output, summary = tmp_path / "output", tmp_path / "summary"
    selection = select(READY, ["README.md"], FILTER_SET)
    write_outputs(
        selection,
        ["README.md"],
        {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)},
    )
    lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert json.loads(lines["selection"]) == selection
    assert lines["skippable"] == skippable(selection)
    assert "Selected from 1 changed files." in summary.read_text()
