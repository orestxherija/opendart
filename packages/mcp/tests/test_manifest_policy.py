"""Lock review rules: versions, unbumped changes, bump sizes, removals, budget, integrity."""

from __future__ import annotations

import pytest

from opendart_mcp.manifest import Finding, blocking, review
from opendart_mcp.versioning.model import component_record, make_manifest, server_record

BUDGET = 10_000
SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": False,
}


def tool(version="1.0.0", *, name="find", optional=False, **updates):
    definition = {
        "name": name,
        "description": "Find things.",
        "inputSchema": SCHEMA,
        "_meta": {"fastmcp": {"tags": [], "version": version}},
    } | updates
    record = component_record("tool", name, version=version, definition=definition)
    return record.model_copy(update={"optional": optional})


def prompt(version="1.0.0"):
    definition = {"name": "brief", "_meta": {"fastmcp": {"version": version}}}
    return component_record("prompt", "brief", version=version, definition=definition)


def manifest(*records, instructions="Use the tools.", version="0.1.0"):
    components = {f"{r.kind}:{r.name}@{r.version or ""}": r for r in records}
    return make_manifest(server_record("Fake", version, instructions), components)


def codes(findings):
    return [(f.code, f.key) for f in findings]


def test_an_identical_server_has_no_findings():
    assert review(manifest(tool(), prompt()), manifest(tool(), prompt()), budget=BUDGET) == []


def test_without_a_lock_every_component_is_new():
    findings = review(None, manifest(tool(), prompt()), budget=BUDGET)
    assert codes(findings) == [("added", "prompt:brief@1.0.0"), ("added", "tool:find@1.0.0")]


@pytest.mark.parametrize(
    ("version", "message"),
    [
        (None, 'declares no version; add version="1.0.0"'),
        ("1.0", "version '1.0' is not MAJOR.MINOR.PATCH"),
        ("v1.0.0", "version 'v1.0.0' is not MAJOR.MINOR.PATCH"),
    ],
)
def test_every_component_needs_a_semantic_version(version, message):
    findings = review(None, manifest(tool(version)), budget=BUDGET)
    assert findings[0] == Finding("invalid-version", f"tool:find@{version or ""}", message)


def test_default_tools_must_fit_the_token_budget():
    current = manifest(tool(), tool(name="huge", optional=True, description="x" * 4000))
    assert review(current, current, budget=500) == []
    big = manifest(tool(description="x" * 4000))
    (finding,) = review(big, big, budget=500)
    assert finding.code == "budget"
    assert "over the 500 budget" in finding.message


def test_a_definition_cannot_change_under_a_recorded_version():
    (finding,) = review(manifest(tool()), manifest(tool(description="Other.")), budget=BUDGET)
    assert finding.code == "changed"
    assert finding.key == "tool:find@1.0.0"
    assert "(description)" in finding.message
    assert "bump version= to 1.0.1 or higher (PATCH: description: changed)" in finding.message


def test_the_suggested_version_follows_the_schema_change():
    schema = {**SCHEMA, "properties": {"text": {"type": "string"}}, "required": ["text"]}
    (finding,) = review(manifest(tool()), manifest(tool(inputSchema=schema)), budget=BUDGET)
    assert (
        "bump version= to 2.0.0 or higher (MAJOR: inputSchema.query: property removed"
        in finding.message
    )
    assert {c.path for c in finding.changes} == {"inputSchema.query", "inputSchema.text"}


def test_a_sufficient_bump_is_a_new_version():
    findings = review(
        manifest(tool()), manifest(tool("1.0.1", description="Other.")), budget=BUDGET
    )
    assert codes(findings) == [("new-version", "tool:find@1.0.1")]
    assert "new version of 1.0.0 (PATCH change) not recorded" in findings[0].message


def test_a_bump_without_definition_changes_is_allowed():
    (finding,) = review(manifest(tool()), manifest(tool("2.0.0")), budget=BUDGET)
    assert finding.code == "new-version"
    assert "no definition change" in finding.message


def test_a_bump_smaller_than_the_change_is_refused():
    schema = {**SCHEMA, "properties": {}, "required": []}
    (finding,) = review(
        manifest(tool()), manifest(tool("1.1.0", inputSchema=schema)), budget=BUDGET
    )
    assert finding.code == "bump"
    assert finding.message.startswith(
        "MINOR bump from 1.0.0 is smaller than the change requires (MAJOR:"
    )
    assert finding.message.endswith('use version="2.0.0" or higher')


def test_a_version_must_increase():
    (finding,) = review(manifest(tool("1.2.0")), manifest(tool("1.1.0")), budget=BUDGET)
    assert finding == Finding(
        "bump", "tool:find@1.1.0", "version must be higher than the recorded 1.2.0"
    )


def test_a_new_version_is_compared_with_the_highest_lower_version():
    lock = manifest(tool("1.0.0", description="Old."), tool("2.0.0"))
    current = manifest(
        tool("1.0.0", description="Old."), tool("2.0.0"), tool("2.1.0", description="New.")
    )
    (finding,) = review(lock, current, budget=BUDGET)
    assert finding.code == "new-version"
    assert "new version of 2.0.0" in finding.message


def test_replacing_a_version_is_not_a_removal():
    findings = review(manifest(tool("1.0.0")), manifest(tool("1.0.1")), budget=BUDGET)
    assert codes(findings) == [("new-version", "tool:find@1.0.1")]


def test_dropping_an_older_version_is_a_removal():
    findings = review(
        manifest(tool("1.0.0"), tool("2.0.0")), manifest(tool("2.0.0")), budget=BUDGET
    )
    assert codes(findings) == [("removed", "tool:find@1.0.0")]
    assert "clients that pin it" in findings[0].message


def test_removing_a_component_is_reported():
    findings = review(manifest(tool(), prompt()), manifest(tool()), budget=BUDGET)
    assert codes(findings) == [("removed", "prompt:brief@1.0.0")]


def test_a_new_component_is_reported():
    findings = review(manifest(tool()), manifest(tool(), prompt()), budget=BUDGET)
    assert codes(findings) == [("added", "prompt:brief@1.0.0")]


def test_unversioned_records_are_not_classified():
    lock = manifest(tool(None))
    findings = review(lock, manifest(tool("1.0.0")), budget=BUDGET)
    assert codes(findings) == [("new-version", "tool:find@1.0.0")]
    assert findings[0].message == "new version not recorded in the lock"


def test_server_changes_name_the_fields():
    (finding,) = review(
        manifest(tool()), manifest(tool(), instructions="New.", version="0.2.0"), budget=BUDGET
    )
    assert finding == Finding(
        "server", "server", "instructions_sha256, instructions_tokens changed; record with --update"
    )


def test_a_release_version_bump_alone_needs_no_lock_update():
    assert review(manifest(tool()), manifest(tool(), version="0.2.0"), budget=BUDGET) == []


def test_hand_edited_lock_entries_are_detected():
    record = tool()
    edited = record.model_copy(
        update={"definition": {**record.definition, "description": "Edited."}}
    )
    findings = review(manifest(edited), manifest(record), budget=BUDGET)
    assert ("integrity", "tool:find@1.0.0") in codes(findings)


def test_checks_fail_on_every_finding_and_updates_only_on_unreviewed_changes():
    codes = ("invalid-version", "budget", "changed", "bump", "added", "removed", "server")
    findings = [
        Finding(code, f"key-{code}", "message") for code in (*codes, "missing", "unreadable")
    ]
    assert blocking(findings, update=False, accept=False) == findings
    refused = blocking(findings, update=True, accept=False)
    assert [f.code for f in refused] == [
        "invalid-version",
        "budget",
        "changed",
        "bump",
        "missing",
        "unreadable",
    ]
    refused = blocking(findings, update=True, accept=True)
    assert [f.code for f in refused] == ["invalid-version", "budget"]
    assert str(findings[0]) == "key-invalid-version: message"


def test_without_a_lock_an_update_needs_acceptance():
    # The caller reports why there is no lock; that finding alone refuses an update, because
    # every component would otherwise be recorded as new, reviewed or not.
    findings = [
        *review(None, manifest(tool()), budget=BUDGET),
        Finding("unreadable", "components.lock.json", "unreadable"),
    ]
    assert codes(blocking(findings, update=True, accept=False)) == [
        ("unreadable", "components.lock.json")
    ]
    assert blocking(findings, update=True, accept=True) == []


def test_a_rewritten_but_equivalent_definition_needs_a_patch():
    optional = {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}
    old = {**SCHEMA, "properties": {**SCHEMA["properties"], "market": optional}}
    new = {**SCHEMA, "properties": {**SCHEMA["properties"], "market": {"type": ["string", "null"]}}}
    (finding,) = review(
        manifest(tool(inputSchema=old)), manifest(tool(inputSchema=new)), budget=BUDGET
    )
    assert finding.code == "changed"
    assert finding.changes == ()
    assert finding.message.endswith(
        "bump version= to 1.0.1 or higher (PATCH: equivalent definitions written differently)"
    )
