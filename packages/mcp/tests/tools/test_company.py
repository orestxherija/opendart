"""find_company, get_company_profile, and the company resource over the MCP protocol."""

from __future__ import annotations

import json

import anyio
import httpx2
import pytest
from fastmcp import Client

from opendart_mcp.server import create_server

PROFILE = {
    "corp_name": "삼성전자",
    "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
    "stock_name": "삼성전자",
    "stock_code": "005930",
    "ceo_nm": "전영현",
    "corp_cls": "Y",
    "jurir_no": "1301110006246",
    "bizr_no": "1248100998",
    "adres": "경기도 수원시 영통구 삼성로 129 (매탄동)",
    "hm_url": "www.samsung.com/sec",
    "ir_url": "",
    "phn_no": "02-2255-0114",
    "fax_no": "031-200-7538",
    "induty_code": "264",
    "est_dt": "19690113",
    "acc_mt": "12",
}


def filing(number, title, filed):
    return {
        "corp_cls": "Y",
        "corp_name": "SAMSUNG ELECTRONICS CO,.LTD",
        "corp_code": "00126380",
        "stock_code": "005930",
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": "삼성전자",
        "rcept_dt": filed,
        "rm": "",
    }


def samsung(upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    upstream.records(
        "/list.json",
        filing("20260814001234", "Semi-Annual Report (2026.06)", "20260814"),
        filing("20260515000456", "Quarterly Report (2026.03)", "20260515"),
        filing("20260310000789", "Annual Report (2025.12)", "20260310"),
    )


@pytest.mark.anyio
async def test_tools_are_listed_in_order_with_versions_and_annotations(client):
    tools = await client.list_tools()
    assert [tool.name for tool in tools[:2]] == ["find_company", "get_company_profile"]
    profile = tools[1]
    assert profile.meta is not None
    assert profile.meta["fastmcp"]["version"] == "1.0.0"
    assert profile.annotations is not None
    assert profile.annotations.read_only_hint is True
    assert profile.annotations.open_world_hint is False
    assert profile.output_schema is not None
    assert {"company", "profile", "as_of"} <= set(profile.output_schema["properties"])
    assert profile.input_schema["required"] == ["company"]


@pytest.mark.anyio
async def test_find_company_picks_a_dominant_match(client, upstream):
    result = await client.call_tool("find_company", {"query": "Samsung Electronics"})
    data = result.structured_content
    assert data["best_match"]["corp_code"] == "00126380"
    assert data["matches"][0]["stock_code"] == "005930"
    assert "| Company | Korean name |" in result.content[0].text
    assert "Best match: SAMSUNG ELECTRONICS" in result.content[0].text
    assert upstream.count() == 1  # the directory download only


@pytest.mark.anyio
async def test_find_company_lists_listed_candidates_first_without_a_winner(client):
    result = await client.call_tool("find_company", {"query": "Samsung", "limit": 5})
    data = result.structured_content
    assert "best_match" not in data
    assert len(data["matches"]) == 5
    assert all(match["listed"] for match in data["matches"])
    assert "No single match dominates" in result.content[0].text
    # Without a market filter only the listing status is known.
    assert "| Listing |" in result.content[0].text
    assert "| listed |" in result.content[0].text


@pytest.mark.anyio
async def test_market_filter_checks_profiles(client, upstream):
    def by_code(request):
        code = request.url.params["corp_code"]
        return upstream.ok(corp_cls="Y" if code in {"00126380", "00149655"} else "K")

    upstream.route("/company.json", by_code)
    result = await client.call_tool(
        "find_company", {"query": "Samsung", "market": "KOSPI", "limit": 2}
    )
    matches = result.structured_content["matches"]
    assert {m["corp_code"] for m in matches} == {"00126380", "00149655"}
    assert all(m["market"] == "KOSPI" for m in matches)
    assert "| KOSPI |" in result.content[0].text


@pytest.mark.anyio
async def test_no_match_is_an_empty_result_with_a_note(client):
    result = await client.call_tool("find_company", {"query": "zzzz nothing"})
    assert result.structured_content["matches"] == []
    assert "No company matches" in result.structured_content["notes"][0]


@pytest.mark.anyio
async def test_profile_includes_the_latest_periodic_report(client, upstream):
    samsung(upstream)
    result = await client.call_tool("get_company_profile", {"company": "005930"})
    data = result.structured_content
    assert data["company"] == {
        "name": "SAMSUNG ELECTRONICS CO,.LTD",
        "korean_name": "삼성전자",
        "corp_code": "00126380",
        "stock_code": "005930",
        "market": "KOSPI",
    }
    assert data["profile"]["established"] == "1969-01-13"
    assert data["profile"]["fiscal_year_end_month"] == 12
    assert "ir_url" not in data["profile"]
    report = data["latest_periodic_report"]
    assert (report["period"], report["fiscal_year"], report["period_end"]) == (
        "H1",
        2026,
        "2026-06-30",
    )
    assert data["source_filings"][0]["filing_number"] == "20260814001234"
    query = upstream.params("/list.json")[0]
    assert (query["corp_code"], query["pblntf_ty"], query["last_reprt_at"]) == (
        "00126380",
        "A",
        "Y",
    )
    text = result.content[0].text
    assert "SAMSUNG ELECTRONICS CO,.LTD (005930, KOSPI; DART 00126380)" in text
    assert 'period="latest" refers to it' in text


@pytest.mark.anyio
async def test_ambiguous_names_return_candidates(client):
    result = await client.call_tool(
        "get_company_profile", {"company": "Samsung"}, raise_on_error=False
    )
    assert result.is_error
    message = result.content[0].text
    assert "Ambiguous company" in message
    assert "00126380" in message


@pytest.mark.anyio
async def test_unknown_codes_are_reported(client):
    result = await client.call_tool(
        "get_company_profile", {"company": "999999"}, raise_on_error=False
    )
    assert result.is_error
    assert "find_company" in result.content[0].text


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    server = create_server(mcp_settings, transport=upstream.transport)
    async with Client(server) as client:
        result = await client.call_tool("find_company", {"query": "Samsung"}, raise_on_error=False)
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text
    assert upstream.count() == 0


@pytest.mark.anyio
async def test_corp_codes_work_while_the_directory_loads(mcp_settings, sdk_settings, upstream, now):
    gate = anyio.Event()

    async def stalled(request):
        await gate.wait()
        return httpx2.Response(500)

    samsung(upstream)
    upstream.route("/corpCode.xml", stalled)
    server = create_server(
        mcp_settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )
    async with Client(server) as client:
        result = await client.call_tool("get_company_profile", {"company": "00126380"})
    assert result.structured_content["company"]["stock_code"] == "005930"


@pytest.mark.anyio
async def test_company_resource_serves_the_profile(client, upstream):
    samsung(upstream)
    (content,) = await client.read_resource("opendart://company/00126380")
    assert content.mime_type == "application/json"
    data = json.loads(content.text)
    assert data["company"]["corp_code"] == "00126380"
    assert data["latest_periodic_report"]["filing_number"] == "20260814001234"
