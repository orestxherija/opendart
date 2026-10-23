"""markdown_view: Markdown text for the model, compact structured content, model schemas."""

from __future__ import annotations

import logging

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult, tool
from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
from pydantic import BaseModel

from opendart_mcp.app.elicitation import InputRequiredError
from opendart_mcp.app.views import markdown_view, structured
from opendart_mcp.core.errors import CompanyNotFoundError

NOT_FOUND = "No company matches 'zz'; call find_company to search the directory."
PENDING = InputRequiredResult(
    result_type="input_required",
    input_requests={
        "company": ElicitRequest(
            params=ElicitRequestFormParams(
                message="Which company?",
                requested_schema={
                    "type": "object",
                    "properties": {"corp_code": {"type": "string"}},
                },
            )
        )
    },
)


class Item(BaseModel):
    name: str
    note: str | None = None


class Listing(BaseModel):
    items: list[Item]
    total: int
    caveat: str | None = None


def render(result: Listing) -> str:
    return "\n".join(f"- {item.name}" for item in result.items)


@tool(name="list_items", version="1.0.0")
@markdown_view(render)
async def list_items(*, limit: int = 2, fail: bool = False, ask: bool = False) -> Listing:
    """List items.

    Args:
        limit: Items to return.
        fail: Raise a domain failure.
        ask: Ask the user for input.
    """
    if fail:
        raise CompanyNotFoundError(NOT_FOUND)
    if ask:
        raise InputRequiredError(PENDING)
    return Listing(items=[Item(name="a"), Item(name="b", note="kept")][:limit], total=limit)


@pytest.fixture
def server(wired):
    server = wired()
    server.add_tool(list_items)
    return server


def test_structured_content_drops_nulls_at_every_level():
    listing = Listing(items=[Item(name="a"), Item(name="b", note="kept")], total=2)
    assert structured(listing) == {
        "items": [{"name": "a"}, {"name": "b", "note": "kept"}],
        "total": 2,
    }


@pytest.mark.anyio
async def test_text_is_markdown_and_structured_content_is_compact(server):
    async with Client(server) as client:
        result = await client.call_tool("list_items", {})
    assert result.content[0].text == "- a\n- b"
    assert result.structured_content == {
        "items": [{"name": "a"}, {"name": "b", "note": "kept"}],
        "total": 2,
    }
    assert result.data.total == 2  # the client validated structured content against the schema


@pytest.mark.anyio
async def test_schemas_come_from_the_wrapped_function(server):
    async with Client(server) as client:
        (listed,) = await client.list_tools()
    assert listed.description == "List items."
    assert set(listed.input_schema["properties"]) == {"limit", "fail", "ask"}
    assert listed.input_schema["properties"]["limit"]["description"] == "Items to return."
    output = listed.output_schema
    assert output is not None
    assert set(output["properties"]) == {"items", "total", "caveat"}
    assert output["required"] == ["items", "total"]


@pytest.mark.anyio
async def test_domain_failures_reach_the_model_verbatim(server):
    async with Client(server) as client:
        result = await client.call_tool("list_items", {"fail": True}, raise_on_error=False)
    assert result.is_error
    assert result.content[0].text == NOT_FOUND


@pytest.mark.anyio
async def test_a_domain_failure_becomes_a_quietly_logged_tool_error():
    with pytest.raises(ToolError, match="No company matches") as raised:
        await list_items(fail=True)
    assert raised.value.log_level == logging.INFO
    assert isinstance(raised.value.__cause__, CompanyNotFoundError)


@pytest.mark.anyio
async def test_a_pending_input_request_ends_the_round():
    assert await list_items(ask=True) is PENDING


@pytest.mark.anyio
async def test_the_wrapper_returns_a_tool_result_and_keeps_metadata():
    result = await list_items(limit=1)
    assert isinstance(result, ToolResult)
    assert result.structured_content == {"items": [{"name": "a"}], "total": 1}
    assert list_items.__name__ == "list_items"
    assert list_items.__wrapped__.__doc__.startswith("List items.")


@tool(name="crash", version="1.0.0")
@markdown_view(render)
async def crash() -> Listing:
    """Fail unexpectedly."""
    raise KeyError("internal detail")


@pytest.mark.anyio
async def test_unexpected_failures_are_left_to_fastmcp():
    with pytest.raises(KeyError, match="internal detail"):
        await crash()
