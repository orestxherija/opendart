"""Component definition diffs and semantic-version helpers."""

from __future__ import annotations

import pytest

from opendart_mcp.versioning.changes import bump_level, diff_definition, next_version, parse_version
from opendart_mcp.versioning.levels import Level, required_level

MAJOR, MINOR, PATCH, NONE = Level.MAJOR, Level.MINOR, Level.PATCH, Level.NONE

TOOL = {
    "name": "find",
    "title": "Find",
    "description": "Find things.",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "outputSchema": {"type": "object", "properties": {"n": {"type": "integer"}}},
    "annotations": {"readOnlyHint": True},
    "_meta": {"fastmcp": {"tags": ["identity"], "version": "1.0.0"}},
}


def changed(**updates):
    return {**TOOL, **updates}


def level(old, new):
    return required_level(diff_definition(old, new))


def test_only_the_version_changed():
    bumped = changed(_meta={"fastmcp": {"tags": ["identity"], "version": "1.0.1"}})
    assert diff_definition(TOOL, bumped) == []


@pytest.mark.parametrize(
    "updates",
    [
        {"description": "Find other things."},
        {"title": "Search"},
        {"annotations": {"readOnlyHint": False}},
        {"_meta": {"fastmcp": {"tags": ["other"], "version": "1.0.0"}}},
        {"icons": [{"src": "https://example.com/i.png"}]},
    ],
)
def test_descriptive_parts_are_patch(updates):
    assert level(TOOL, changed(**updates)) is PATCH


def test_a_description_change_is_reported_without_its_text():
    (change,) = diff_definition(TOOL, changed(description="Other."))
    assert (change.path, change.detail) == ("description", "changed")


def test_input_schema_changes_are_classified():
    schema = {**TOOL["inputSchema"], "properties": {}, "required": []}
    (change,) = diff_definition(TOOL, changed(inputSchema=schema))
    assert (change.level, change.path, change.detail) == (
        MAJOR,
        "inputSchema.query",
        "property removed",
    )


def test_output_schemas_can_be_added_changed_or_removed():
    without = {key: value for key, value in TOOL.items() if key != "outputSchema"}
    assert level(without, TOOL) is MINOR
    assert level(TOOL, without) is MAJOR
    schema = {"type": "object", "properties": {"n": {"type": "string"}}}
    assert level(TOOL, changed(outputSchema=schema)) is MAJOR


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (None, "optional", MINOR),
        ("optional", "required", MAJOR),
        (None, "required", MAJOR),
        ("required", "optional", MINOR),
        ("optional", None, MINOR),
    ],
)
def test_task_support(old, new, expected):
    def execution(support):
        return {} if support is None else {"execution": {"taskSupport": support}}

    assert level({**TOOL, **execution(old)}, {**TOOL, **execution(new)}) is expected


def test_mime_type_changes_are_major():
    resource = {"name": "about", "uri": "x://about", "mimeType": "text/plain"}
    assert level(resource, {**resource, "mimeType": "application/json"}) is MAJOR
    assert level(resource, {**resource, "name": "About"}) is PATCH
    assert level(resource, {**resource, "size": 10}) is PATCH


def prompt(*arguments):
    return {"name": "brief", "arguments": list(arguments)}


COMPANY = {"name": "company", "required": True, "description": "Company."}
SINCE = {"name": "since", "description": "Start."}


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (prompt(COMPANY, SINCE), prompt(COMPANY), MAJOR),
        (prompt(COMPANY), prompt(COMPANY, SINCE), MINOR),
        (prompt(SINCE), prompt(SINCE, COMPANY), MAJOR),
        (prompt(SINCE), prompt({**SINCE, "required": True}), MAJOR),
        (prompt(COMPANY), prompt({**COMPANY, "required": False}), MINOR),
        (prompt(COMPANY), prompt({**COMPANY, "description": "Name."}), PATCH),
        (prompt(COMPANY, SINCE), prompt(SINCE, COMPANY), PATCH),
        (prompt(COMPANY), {"name": "brief"}, MAJOR),
    ],
)
def test_prompt_arguments(old, new, expected):
    assert level(old, new) is expected


def test_prompt_argument_details():
    changes = diff_definition(prompt(COMPANY), prompt({**COMPANY, "required": False}))
    assert [(c.path, c.detail) for c in changes] == [("arguments.company", "optional")]
    changes = diff_definition(prompt(COMPANY, SINCE), prompt(SINCE, COMPANY))
    assert [(c.path, c.detail) for c in changes] == [("arguments", "argument order changed")]


def test_other_top_level_changes_are_minor():
    assert level(TOOL, changed(uri="x://other")) is MINOR


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.0.0", (1, 0, 0)),
        ("10.20.30", (10, 20, 30)),
        ("0.1.0", (0, 1, 0)),
        ("1.0", None),
        ("1.0.0-rc1", None),
        ("01.0.0", None),
        ("v1.0.0", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("1.0.0", "2.0.0", MAJOR),
        ("1.2.3", "2.0.0", MAJOR),
        ("1.0.0", "1.1.0", MINOR),
        ("1.0.9", "1.1.0", MINOR),
        ("1.0.0", "1.0.1", PATCH),
        ("1.0.0", "1.0.0", None),
        ("1.1.0", "1.0.9", None),
        ("1.0", "1.1.0", None),
    ],
)
def test_bump_level(old, new, expected):
    assert bump_level(old, new) == expected


@pytest.mark.parametrize(
    ("version", "level", "expected"),
    [
        ("1.2.3", MAJOR, "2.0.0"),
        ("1.2.3", MINOR, "1.3.0"),
        ("1.2.3", PATCH, "1.2.4"),
        ("1.2.3", NONE, "1.2.3"),
        ("bad", MAJOR, "bad"),
    ],
)
def test_next_version(version, level, expected):
    assert next_version(version, level) == expected


def test_meta_without_a_fastmcp_namespace_is_compared_as_is():
    plain = {k: v for k, v in TOOL.items() if k != "_meta"}
    assert level({**plain, "_meta": {"other": 1}}, {**plain, "_meta": {"other": 2}}) is PATCH
    assert level(plain, {**plain, "_meta": {"other": 1}}) is PATCH
