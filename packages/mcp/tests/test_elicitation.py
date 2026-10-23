"""Choosing among ambiguous companies through elicitation, in both protocol eras."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from opendart_mcp.app.elicitation import _answers
from opendart_mcp.server import create_server
from opendart_mcp.settings import Settings, ToolSettings

SAMSUNG_ELECTRONICS = "00126380"


def accept(code=SAMSUNG_ELECTRONICS, asked=None):
    async def handler(message, response_type, params, context):
        if asked is not None:
            asked.append(message)
        try:  # 2026-07-28 guard requests carry our object schema
            content = response_type(corp_code=code)
        except TypeError:  # 2025-11-25 ctx.elicit with a list of choices
            content = response_type(value=code)
        return ElicitResult(action="accept", content=content)

    return handler


async def decline(message, response_type, params, context):
    return ElicitResult(action="decline")


def profile(upstream):
    upstream.route("/company.json", upstream.ok(corp_name="삼성전자", corp_cls="Y", acc_mt="12"))


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.anyio
async def test_the_user_picks_a_company(server, upstream, mode):
    profile(upstream)
    asked: list[str] = []
    async with Client(server, mode=mode, elicitation_handler=accept(asked=asked)) as client:
        result = await client.call_tool("get_company_profile", {"company": "Samsung"})
    assert result.structured_content["company"]["corp_code"] == SAMSUNG_ELECTRONICS
    assert asked == ["'Samsung' matches several companies. Which one do you mean?"]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.anyio
async def test_declining_falls_back_to_the_candidate_list(server, mode):
    async with Client(server, mode=mode, elicitation_handler=decline) as client:
        result = await client.call_tool(
            "get_company_profile", {"company": "Samsung"}, raise_on_error=False
        )
    assert result.is_error
    assert "Ambiguous company 'Samsung'" in result.content[0].text


@pytest.mark.anyio
async def test_an_unexpected_answer_falls_back_to_the_candidate_list(server):
    async with Client(server, elicitation_handler=accept(code="99999999")) as client:
        result = await client.call_tool(
            "get_company_profile", {"company": "Samsung"}, raise_on_error=False
        )
    assert result.is_error
    assert "Ambiguous company" in result.content[0].text


@pytest.mark.anyio
async def test_a_failing_elicitation_falls_back_to_the_candidate_list(server):
    async def broken(message, response_type, params, context):
        raise RuntimeError("the host's dialog failed")

    async with Client(server, mode="legacy", elicitation_handler=broken) as client:
        result = await client.call_tool(
            "get_company_profile", {"company": "Samsung"}, raise_on_error=False
        )
    assert result.is_error
    assert "Ambiguous company 'Samsung'" in result.content[0].text


@pytest.mark.parametrize("stored", ["not json", '["a list"]', '{"Samsung": 1}'])
def test_a_malformed_request_state_holds_no_answers(stored):
    assert _answers(SimpleNamespace(request_state=stored, input_responses=None)) == {}


@pytest.mark.anyio
async def test_hosts_without_elicitation_get_candidates(client):
    result = await client.call_tool(
        "get_company_profile", {"company": "Samsung"}, raise_on_error=False
    )
    assert result.is_error
    assert "Re-call with a stock code or corp code" in result.content[0].text


@pytest.mark.anyio
async def test_elicitation_can_be_disabled(mcp_settings, sdk_settings, upstream, now):
    settings = Settings(
        http=mcp_settings.http,
        directory=mcp_settings.directory,
        tasks=mcp_settings.tasks,
        tools=ToolSettings(elicit_ambiguous_company=False),
    )
    upstream.route("/corpCode.xml", upstream.corp_archive())
    server = create_server(
        settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )
    asked: list[str] = []
    async with Client(server, elicitation_handler=accept(asked=asked)) as client:
        result = await client.call_tool(
            "get_company_profile", {"company": "Samsung"}, raise_on_error=False
        )
    assert result.is_error
    assert asked == []


def answer_by_query(asked, schemas):
    choices = {"Samsung": SAMSUNG_ELECTRONICS, "삼성": "00149655"}

    async def handler(message, response_type, params, context):
        asked.append(message)
        schemas.append(params.requested_schema)
        code = next(code for query, code in choices.items() if f"'{query}'" in message)
        try:
            content = response_type(corp_code=code)
        except TypeError:
            content = response_type(value=code)
        return ElicitResult(action="accept", content=content)

    return handler


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.anyio
async def test_several_ambiguous_companies_are_asked_once_each(server, mode):
    # compare_companies runs in the foreground; background tasks have no session to ask.
    asked: list[str] = []
    schemas: list[dict] = []
    handler = answer_by_query(asked, schemas)
    async with Client(server, mode=mode, elicitation_handler=handler) as client:
        result = await client.call_tool(
            "compare_companies", {"companies": ["Samsung", "삼성"]}, raise_on_error=False
        )
    assert not result.is_error
    assert sorted(asked) == sorted(
        f"'{query}' matches several companies. Which one do you mean?"
        for query in ("Samsung", "삼성")
    )
    options = next(iter(schemas[0]["properties"].values()))["oneOf"]
    assert all("corp" in option["title"] for option in options)
