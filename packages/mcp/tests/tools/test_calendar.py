"""get_corporate_action_calendar over the MCP protocol: dates, filters, watchlists, errors."""

from __future__ import annotations

import anyio
import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp_tasks import call_tool_task

from opendart_mcp.server import create_server
from opendart_mcp.settings import Settings, UpstreamSettings
from opendart_mcp.tools import calendar as calendar_tool
from scripts.testing.events import (
    HYNIX,
    SAMSUNG,
    buyback,
    convertible_bond,
    filing,
    identity,
    merger,
    profile,
)

WATCHLIST = ["005930", "000660"]


class NoTasksClient(Client[FastMCPTransport]):
    """A modern client without the tasks extension, like Claude hosts today."""

    _auto_internal_extensions = False


def by_company(upstream, table):
    """Answer a route with records chosen by the corp_code parameter."""

    def answer(request):
        records = table.get(request.url.params.get("corp_code"), [])
        return upstream.rows(*records) if records else upstream.status("013")

    return answer


def watchlist(upstream):
    companies = {SAMSUNG[0]: SAMSUNG, HYNIX[0]: HYNIX}
    upstream.route(
        "/company.json",
        lambda request: upstream.ok(**profile(companies[request.url.params["corp_code"]])),
    )
    major = {
        SAMSUNG[0]: [
            filing("20260915000123", "Decision on Issuance of Convertible Bonds"),
            filing("20260901000456", "Decision on Merger"),
            filing("20260801000001", "Lawsuit Filing, etc."),
        ],
        HYNIX[0]: [filing("20261019000305", "Decision on Acquisition of Treasury Stock", HYNIX)],
    }

    def index(request):
        if request.url.params.get("pblntf_ty") != "B":
            return upstream.status("013")
        return by_company(upstream, major)(request)

    upstream.route("/list.json", index)
    upstream.route("/cvbdIsDecsn.json", by_company(upstream, {SAMSUNG[0]: [convertible_bond()]}))
    upstream.route("/cmpMgDecsn.json", by_company(upstream, {SAMSUNG[0]: [merger()]}))
    upstream.route("/tsstkAqDecsn.json", by_company(upstream, {HYNIX[0]: [buyback()]}))


async def call(client, **arguments):
    result = await client.call_tool(
        "get_corporate_action_calendar",
        {"companies": WATCHLIST, **arguments},
        raise_on_error=False,
    )
    return result, result.structured_content


def rows(data):
    return [(i["date"], i["company"]["stock_code"], i["action"]) for i in data["items"]]


@pytest.mark.anyio
async def test_the_tool_is_listed_with_its_schema(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    calendar = tools["get_corporate_action_calendar"]
    assert calendar.meta["fastmcp"]["version"] == "1.0.1"
    assert calendar.annotations.read_only_hint is True
    assert calendar.input_schema["required"] == ["companies"]
    assert calendar.input_schema["properties"]["horizon"]["default"] == "90d"
    assert {"items", "horizon_days", "start", "end"} <= set(calendar.output_schema["properties"])
    assert 60 <= len(calendar.description.split()) <= 120


@pytest.mark.anyio
async def test_dates_within_the_horizon_are_sorted(client, upstream):
    watchlist(upstream)
    result, data = await call(client)
    assert not result.is_error
    assert rows(data) == [
        ("2026-11-03", "005930", "record_date"),
        ("2026-11-03", "005930", "objection_start"),
        ("2026-11-12", "005930", "subscription"),
        ("2026-11-12", "005930", "payment_date"),
        ("2026-11-17", "005930", "objection_end"),
        ("2026-11-20", "005930", "creditor_objection_start"),
        ("2026-12-21", "005930", "creditor_objection_end"),
        ("2026-12-22", "005930", "effective_date"),
        ("2027-01-08", "005930", "listing_date"),
        ("2027-01-20", "000660", "buyback_end"),
    ]
    assert (data["start"], data["end"], data["horizon_days"]) == ("2026-10-22", "2027-01-20", 90)
    item = data["items"][2]
    assert item["company"]["corp_code"] == "00126380"
    assert item["source_kind"] == "convertible_bond"
    assert item["dart_url"].endswith("rcpNo=20260915000123")
    assert item["details"] == {
        "event": "Convertible bond",
        "face_value": 30000000000,
        "series": "3",
        "coupon_pct": 1.5,
    }
    assert upstream.count("/lwstLg.json") == 0  # lawsuits carry no calendar dates
    assert "filings made since 2025-10-22" in data["notes"][0]
    assert not any("maturities are not included" in note for note in data["notes"])
    text = result.content[0].text
    assert "| Date | Company | Action | Event | Terms | Filing |" in text
    assert "Dissent notice period opens" in text


@pytest.mark.anyio
async def test_include_past_and_a_dated_horizon(client, upstream):
    watchlist(upstream)
    _, data = await call(client, include_past="30d", horizon="2026-11-05")
    assert rows(data) == [
        ("2026-10-20", "000660", "buyback_start"),
        ("2026-11-03", "005930", "record_date"),
        ("2026-11-03", "005930", "objection_start"),
    ]
    assert (data["start"], data["horizon_days"]) == ("2026-09-22", 14)
    assert "filings made since 2025-09-22" in data["notes"][0]
    assert "other bonds, since 2023-09-22" in data["notes"][0]
    # One index search over the bond window picks the kinds for both windows.
    index = [p for p in upstream.params("/list.json") if p.get("pblntf_ty") in {"B", "C"}]
    assert len(index) == 4  # B and C for each company
    assert {(p["pblntf_ty"], p["bgn_de"]) for p in index} == {("B", "20230922"), ("C", "20230922")}
    assert upstream.params("/tsstkAqDecsn.json")[0]["bgn_de"] == "20250922"
    assert upstream.params("/cvbdIsDecsn.json")[0]["bgn_de"] == "20230922"


@pytest.mark.anyio
async def test_kinds_skip_the_index_and_drop_kinds_without_dates(client, upstream):
    watchlist(upstream)
    _, data = await call(client, kinds=["buyback", "lawsuit"])
    assert rows(data) == [("2027-01-20", "000660", "buyback_end")]
    # No filing index, and no debt record: kinds without debt_maturity leave maturities out.
    assert upstream.count("/list.json") == 0
    assert upstream.count("/detScritsIsuAcmslt.json") == 0
    assert upstream.count("/lwstLg.json") == 0
    assert "Left out kinds without calendar dates: lawsuit." in data["notes"]


@pytest.mark.anyio
async def test_an_empty_calendar_says_so(client, upstream):
    watchlist(upstream)
    _, data = await call(client, companies=["000660"], horizon="2026-11-30")
    assert data["items"] == []
    assert data["notes"][-1] == "No corporate-action dates from 2026-10-22 to 2026-11-30."


@pytest.mark.anyio
async def test_a_registration_statement_does_not_repeat_its_decisions_dates(client, upstream):
    watchlist(upstream)
    general = {
        "rcept_no": "20261015000123",
        **identity(),
        "stn": "Merger",
        "gmtsck_shddstd": "2026.11.03",
        "mgdt_etc": "2026.12.22",
        "rpt_rcpn": "20260901000456",
    }
    upstream.records("/mgRs.json", group=[{"title": "General matters", "list": [general]}])
    _, data = await call(
        client, companies=["005930"], kinds=["merger", "merger_registration"], horizon="6m"
    )
    dated = [(i["date"], i["action"]) for i in data["items"]]
    assert len(dated) == len(set(dated)) == 7
    assert {i["source_kind"] for i in data["items"]} == {"merger"}
    effective = next(i for i in data["items"] if i["action"] == "effective_date")
    assert effective["filing_number"] == "20260901000456"
    assert effective["details"]["registration_filing"] == "20261015000123"


@pytest.mark.anyio
async def test_duplicate_companies_are_merged(client, upstream):
    watchlist(upstream)
    _, data = await call(client, companies=["005930", "00126380", "A005930"], kinds=["merger"])
    assert [c["corp_code"] for c in data["companies"]] == ["00126380"]
    assert data["notes"][0] == "Merged 2 duplicate companies."


@pytest.mark.anyio
async def test_the_item_count_is_capped(client, upstream):
    watchlist(upstream)
    bonds = [convertible_bond(f"20260915{n:06d}") for n in range(101)]
    upstream.route("/cvbdIsDecsn.json", by_company(upstream, {SAMSUNG[0]: bonds}))
    _, data = await call(client, companies=["005930"], kinds=["convertible_bond"])
    assert len(data["items"]) == 200
    assert "Showing the first 200 of 202 dates" in data["notes"][-1]


@pytest.mark.anyio
async def test_progress_is_reported_per_company(server, upstream):
    watchlist(upstream)
    messages: list[str | None] = []

    async def on_progress(progress, total, message):
        messages.append(message)

    async with NoTasksClient(server, progress_handler=on_progress) as client:
        await client.call_tool("get_corporate_action_calendar", {"companies": WATCHLIST})
    reported = sorted(m for m in messages if m and m[1] == "/")
    assert reported in (
        ["1/2 SAMSUNG ELECTRONICS CO,.LTD", "2/2 SK hynix Inc."],
        ["1/2 SK hynix Inc.", "2/2 SAMSUNG ELECTRONICS CO,.LTD"],
    )


@pytest.mark.anyio
async def test_runs_as_a_background_task(client, upstream):
    watchlist(upstream)
    task = await call_tool_task(client, "get_corporate_action_calendar", {"companies": WATCHLIST})
    result = await task.result()
    assert len(result.structured_content["items"]) == 10


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"companies": ["005930", "Samsung"]}, "Ambiguous company 'Samsung'"),
        ({"horizon": "soon"}, "horizon: Invalid date 'soon'"),
        ({"horizon": "2026-01-01"}, "is before today"),
        ({"include_past": "2027-01-01"}, "is after today"),
        ({"include_past": "lately"}, "include_past: Invalid date 'lately'"),
        ({"kinds": ["lawsuit"]}, "lawsuit reports carry no calendar dates"),
        ({"kinds": ["cb"]}, "Unknown event categories: cb"),
        ({"companies": ["005930", "999999"]}, "find_company"),
    ],
)
async def test_invalid_arguments_are_explained(client, upstream, arguments, expected):
    watchlist(upstream)
    result, _ = await call(client, **arguments)
    assert result.is_error
    assert expected in result.content[0].text


@pytest.mark.anyio
async def test_a_failing_company_is_noted_while_the_others_answer(
    mcp_settings, sdk_settings, upstream, now
):
    settings = Settings(
        http=mcp_settings.http,
        directory=mcp_settings.directory,
        tasks=mcp_settings.tasks,
        upstream=UpstreamSettings(retry_delay=0),
    )
    watchlist(upstream)
    upstream.route("/corpCode.xml", upstream.corp_archive())
    fallback = upstream.routes["/list.json"]

    def index(request):
        if request.url.params.get("corp_code") == HYNIX[0]:
            return httpx2.Response(503)
        return fallback(request)

    upstream.route("/list.json", index)
    server = create_server(
        settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )
    async with Client(server) as client:
        result, data = await call(client)
    assert not result.is_error
    assert {i["company"]["stock_code"] for i in data["items"]} == {"005930"}
    assert any(
        note.startswith("No dates for SK hynix Inc.: OpenDART did not respond")
        for note in data["notes"]
    )


@pytest.mark.anyio
async def test_failed_reports_are_noted(mcp_settings, sdk_settings, upstream, now):
    settings = Settings(
        http=mcp_settings.http,
        directory=mcp_settings.directory,
        tasks=mcp_settings.tasks,
        upstream=UpstreamSettings(retry_delay=0),
    )
    watchlist(upstream)
    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/cmpMgDecsn.json", httpx2.Response(503))
    server = create_server(
        settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )
    async with Client(server) as client:
        _, data = await call(client, companies=["005930"])
    assert (
        "OpenDART did not answer for SAMSUNG ELECTRONICS CO,.LTD's merger reports." in data["notes"]
    )
    assert {i["source_kind"] for i in data["items"]} == {"convertible_bond"}


@pytest.mark.anyio
async def test_quota_exhaustion_fails_the_calendar(client, upstream):
    watchlist(upstream)
    upstream.route("/tsstkAqDecsn.json", upstream.status("020"))
    result, _ = await call(client, kinds=["buyback"])
    assert result.is_error
    assert "Retry after 00:00 KST" in result.content[0].text


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    server = create_server(mcp_settings, transport=upstream.transport)
    async with Client(server) as client:
        result, _ = await call(client)
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text


@pytest.mark.anyio
async def test_the_deadline_asks_for_a_retry(server, upstream, monkeypatch):
    watchlist(upstream)
    gate = anyio.Event()

    async def held(request):
        await gate.wait()
        return upstream.status("013")

    upstream.route("/list.json", held)
    monkeypatch.setattr(calendar_tool, "FOREGROUND_DEADLINE", 0.2)
    async with NoTasksClient(server) as client:
        result, _ = await call(client)
        gate.set()
        await anyio.sleep(0.05)
    assert result.is_error
    assert "Reading event filings for 2 companies is still in progress" in result.content[0].text
