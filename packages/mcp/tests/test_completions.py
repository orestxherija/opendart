"""Argument completion for prompts and resource templates."""

from __future__ import annotations

import anyio
import httpx2
import pytest
from fastmcp import Client
from mcp.types import CompletionArgument, PromptReference, ResourceTemplateReference

from opendart_mcp.completions import complete, matching
from opendart_mcp.server import create_server

PROFILE_TEMPLATE = ResourceTemplateReference(
    type="ref/resource", uri="opendart://company/{corp_code}"
)
FILINGS_TEMPLATE = ResourceTemplateReference(
    type="ref/resource", uri="opendart://company/{corp_code}/filings{?since,category}"
)


def prompt(name):
    return PromptReference(type="ref/prompt", name=name)


async def suggest(client, ref, name, value):
    completion = await client.complete(ref, {"name": name, "value": value})
    return completion.values


@pytest.mark.anyio
async def test_the_server_advertises_completions(client):
    assert client.server_capabilities is not None
    assert client.server_capabilities.completions is not None


@pytest.mark.anyio
async def test_corp_codes_complete_from_names_and_codes(client):
    await client.call_tool("find_company", {"query": "NAVER"})  # waits for the directory
    codes = await suggest(client, PROFILE_TEMPLATE, "corp_code", "Samsung Electronics")
    assert codes[0] == "00126380"
    assert set(codes) == {"00126380", "01345812", "00252074"}
    assert await suggest(client, FILINGS_TEMPLATE, "corp_code", "005930") == ["00126380"]
    assert await suggest(client, PROFILE_TEMPLATE, "corp_code", " ") == []


@pytest.mark.anyio
async def test_company_names_list_listed_companies_first(client):
    await client.call_tool("find_company", {"query": "NAVER"})
    names = await suggest(client, prompt("company_briefing"), "company", "samsung elec")
    assert names[0] == "SAMSUNG ELECTRONICS CO,.LTD"
    assert names.index("SAMSUNG ELECTRONICS CO,.LTD") < names.index(
        "SAMSUNG ELECTRONICS SALES Co., Ltd."
    )
    korean = await suggest(client, prompt("earnings_review"), "company", "삼성전")
    assert korean[0] == "삼성전자"
    assert await suggest(client, prompt("company_briefing"), "company", "") == []


@pytest.mark.anyio
async def test_company_lists_complete_their_last_entry(client):
    await client.call_tool("find_company", {"query": "NAVER"})
    values = await suggest(client, prompt("peer_comparison"), "companies", "NAVER, Kak")
    assert values == ["NAVER, Kakao Corp."]
    first = await suggest(client, prompt("watchlist_digest"), "companies", "Celltri")
    assert first == ["Celltrion, Inc."]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("ref", "name", "value", "expected"),
    [
        (prompt("earnings_review"), "period", "q", ["Q1", "Q3"]),
        (prompt("earnings_review"), "period", "", ["latest", "FY", "Q1", "H1", "Q3"]),
        (prompt("pre_trade_checklist"), "direction", "S", ["short"]),
        (prompt("filings_screen"), "market", "kosd", ["KOSDAQ", "KOSPI,KOSDAQ"]),
        (prompt("filings_screen"), "focus", "bu", ["buybacks"]),
        (prompt("peer_comparison"), "focus", "gro", ["growth"]),
        (prompt("event_impact"), "event", "convertible_b", ["convertible_bond"]),
        (FILINGS_TEMPLATE, "category", "treasury", ["treasury_stock", "treasury_trust"]),
        (FILINGS_TEMPLATE, "category", "report", None),
        (prompt("summarize_filing"), "focus", "div", []),
        (FILINGS_TEMPLATE, "since", "9", []),
    ],
)
async def test_closed_vocabularies_complete(client, ref, name, value, expected):
    values = await suggest(client, ref, name, value)
    if expected is None:
        assert values[:3] == ["periodic_reports", "annual_report", "semiannual_report"]
        assert "audit_reports" in values
    else:
        assert values == expected


@pytest.mark.anyio
async def test_nothing_is_suggested_while_the_directory_loads(
    mcp_settings, sdk_settings, upstream, now
):
    gate = anyio.Event()

    async def stalled(request):
        await gate.wait()
        return httpx2.Response(500)

    upstream.route("/corpCode.xml", stalled)
    server = create_server(
        mcp_settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )
    async with Client(server) as client:
        assert await suggest(client, prompt("company_briefing"), "company", "Samsung") == []
        assert await suggest(client, PROFILE_TEMPLATE, "corp_code", "Samsung") == []
        assert await suggest(client, prompt("earnings_review"), "period", "F") == ["FY"]


@pytest.mark.anyio
async def test_the_handler_needs_a_request_context():
    argument = CompletionArgument(name="company", value="Samsung")
    assert await complete(prompt("company_briefing"), argument, None) == []


def test_matching_ranks_prefixes_before_substrings():
    options = ["treasury_stock", "stock_options", "funds"]
    assert matching(options, " STOCK") == ["stock_options", "treasury_stock"]
