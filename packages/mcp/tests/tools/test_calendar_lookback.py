"""The calendar reads bond filings three years back and other event filings one year back."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client

from opendart_mcp.server import create_server
from scripts.testing.events import buyback, convertible_bond, filing, merger, profile

LONG_START = "20231022"
RECENT_START = "20251022"


def windowed(upstream, *rows):
    """Answer an event service with the rows whose filing date is in the queried window."""

    def answer(request):
        low, high = request.url.params["bgn_de"], request.url.params["end_de"]
        found = [row for row in rows if low <= row["rcept_no"][:8] <= high]
        return upstream.rows(*found) if found else upstream.status("013")

    return answer


def private_bond(number, **dates):
    """A convertible bond whose conversion opens a year after a later payment."""
    defaults = {"sbd": "2025.11.12", "pymd": "2025.11.12", "cvrqpd_bgd": "2026.11.12"}
    return convertible_bond(number, **(defaults | dates))


async def calendar(client, **arguments):
    result = await client.call_tool(
        "get_corporate_action_calendar", {"companies": ["005930"], **arguments}
    )
    return result.structured_content


@pytest.mark.anyio
async def test_a_conversion_opening_more_than_a_year_after_the_filing_is_listed(client, upstream):
    upstream.route("/company.json", upstream.ok(**profile()))
    upstream.route("/cvbdIsDecsn.json", windowed(upstream, private_bond("20250915000123")))
    data = await calendar(client, kinds=["convertible_bond"])
    assert [(i["date"], i["action"]) for i in data["items"]] == [("2026-11-12", "conversion_start")]
    assert [p["bgn_de"] for p in upstream.params("/cvbdIsDecsn.json")] == [LONG_START]
    assert data["notes"][0] == (
        "Dates come from convertible, warrant, exchangeable, and other bond filings made since 2023-10-22."
    )
    assert "bonds converted or redeemed early still show them" in data["notes"][1]


@pytest.mark.anyio
async def test_the_opening_stays_listed_until_it_happens(mcp_settings, sdk_settings, upstream):
    """RF Tech's private bonds, filed 2026-10-21, open conversion on 2027-11-12."""
    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/company.json", upstream.ok(**profile()))
    dates = {"sbd": "2026.11.12", "pymd": "2026.11.12", "cvrqpd_bgd": "2027.11.12"}
    upstream.route("/cvbdIsDecsn.json", windowed(upstream, private_bond("20261021000302", **dates)))
    later = datetime(2027, 10, 25, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    server = create_server(
        mcp_settings, api=sdk_settings, transport=upstream.transport, clock=lambda: later
    )
    async with Client(server) as client:
        data = await calendar(client, kinds=["convertible_bond"], horizon="30d")
    assert [(i["date"], i["action"]) for i in data["items"]] == [("2027-11-12", "conversion_start")]


@pytest.mark.anyio
async def test_one_index_search_picks_kinds_for_both_windows(client, upstream):
    upstream.route("/company.json", upstream.ok(**profile()))
    major = [
        filing("20260901000456", "Decision on Merger"),
        filing("20250801000305", "Decision on Acquisition of Treasury Stock"),
        filing("20241201000123", "Decision on Issuance of Convertible Bonds"),
    ]

    def index(request):
        group = request.url.params.get("pblntf_ty")
        return upstream.rows(*major) if group == "B" else upstream.status("013")

    upstream.route("/list.json", index)
    old_bond = private_bond("20241201000123", cvrqpd_bgd="2026.12.01")
    upstream.route("/cvbdIsDecsn.json", windowed(upstream, old_bond))
    upstream.route("/cmpMgDecsn.json", windowed(upstream, merger()))
    upstream.route("/tsstkAqDecsn.json", windowed(upstream, buyback("20250801000305")))
    data = await calendar(client)
    searches = [p for p in upstream.params("/list.json") if p.get("pblntf_ty") in {"B", "C"}]
    assert {p["bgn_de"] for p in searches} == {LONG_START}
    assert [p["bgn_de"] for p in upstream.params("/cvbdIsDecsn.json")] == [LONG_START]
    assert [p["bgn_de"] for p in upstream.params("/cmpMgDecsn.json")] == [RECENT_START]
    # The buyback was filed before the recent window, so its service is not read.
    assert upstream.count("/tsstkAqDecsn.json") == 0
    assert ("2026-12-01", "conversion_start") in [(i["date"], i["action"]) for i in data["items"]]
    assert "registration filings made since 2025-10-22 and, for convertible" in data["notes"][0]


@pytest.mark.anyio
async def test_index_groups_read_in_part_count_as_filed_in_both_windows(client, upstream):
    upstream.route("/company.json", upstream.ok(**profile()))

    def index(request):
        if request.url.params.get("pblntf_ty") != "B":
            return upstream.status("013")
        return upstream.rows(filing("20260901000456", "Decision on Merger"), total_page=5)

    upstream.route("/list.json", index)
    await calendar(client)
    assert [p["bgn_de"] for p in upstream.params("/tsstkAqDecsn.json")] == [RECENT_START]
    assert [p["bgn_de"] for p in upstream.params("/bdwtIsDecsn.json")] == [LONG_START]
    assert upstream.count("/bdRs.json") == 0  # offering statements are group C, read in full
