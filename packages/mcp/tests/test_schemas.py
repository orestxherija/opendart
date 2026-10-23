"""Compact advertised schemas stay equivalent to Pydantic's."""

from __future__ import annotations

import json

import pytest

from opendart_mcp.app.schemas import compact_schema


@pytest.mark.parametrize(
    ("verbose", "compact"),
    [
        (
            {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
            {"type": ["integer", "null"]},
        ),
        (
            {"anyOf": [{"type": "null"}, {"type": "string", "maxLength": 5}], "description": "d"},
            {"type": ["string", "null"], "maxLength": 5, "description": "d"},
        ),
        (
            {"anyOf": [{"enum": ["a", "b"], "type": "string"}, {"type": "null"}]},
            {"enum": ["a", "b", None], "type": ["string", "null"]},
        ),
        (
            {"anyOf": [{"enum": ["a"]}, {"type": "null"}]},
            {"enum": ["a", None]},
        ),
        (
            {"anyOf": [{"type": ["integer", "number"]}, {"type": "null"}]},
            {"type": ["integer", "number", "null"]},
        ),
        (
            {"anyOf": [{"type": "integer"}, {"type": "string"}]},
            {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        ),
        (
            {"anyOf": [{"$ref": "#/$defs/X"}, {"type": "null"}]},
            {"anyOf": [{"$ref": "#/$defs/X"}, {"type": "null"}]},
        ),
        ({"title": "Thing", "type": "object", "default": 3}, {"type": "object", "default": 3}),
        (
            {"anyOf": [{"const": "only", "type": "string"}, {"type": "null"}]},
            {"enum": ["only", None], "type": ["string", "null"]},
        ),
        (
            {"anyOf": [{"not": {"type": "string"}}, {"type": "null"}]},
            {"anyOf": [{"not": {"type": "string"}}, {"type": "null"}]},
        ),
    ],
)
def test_compaction_cases(verbose, compact):
    assert compact_schema(verbose) == compact


def test_property_names_are_never_dropped():
    schema = {
        "type": "object",
        "properties": {
            "title": {"title": "Title", "type": "string"},
            "default": {"type": "integer"},
        },
        "required": ["title"],
    }
    assert compact_schema(schema) == {
        "type": "object",
        "properties": {"title": {"type": "string"}, "default": {"type": "integer"}},
        "required": ["title"],
    }


@pytest.mark.anyio
async def test_listed_schemas_are_already_compact(client):
    tools = await client.list_tools()
    assert tools
    for tool in tools:
        assert compact_schema(tool.input_schema) == tool.input_schema, tool.name
        assert compact_schema(tool.output_schema) == tool.output_schema, tool.name
        assert '"default": null' not in json.dumps(tool.input_schema), tool.name


@pytest.mark.anyio
async def test_structured_results_still_validate_against_compact_schemas(client, upstream):
    upstream.route("/company.json", upstream.ok(corp_name="삼성전자", corp_cls="Y"))
    result = await client.call_tool("get_company_profile", {"company": "00126380"})
    assert result.structured_content["company"]["corp_code"] == "00126380"
    assert "latest_periodic_report" not in result.structured_content
