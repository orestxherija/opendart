"""Debt maturities in get_corporate_action_calendar: coverage notes, kinds, and failures."""

from __future__ import annotations

import pytest

from opendart_mcp.services.calendar_debt import COVERAGE
from packages.mcp.tests.events.data import buyback, filing, identity, merger, profile

HALF_YEAR = "20260814001234"
ANNUAL = "20260310002820"
LADDER_NOTE = "SAMSUNG ELECTRONICS CO,.LTD: KRW 803,572 million of the KRW 1,937,532 million in corporate bonds outstanding at 2026-06-30 was due within a year of that date (H1 2026 report)."


def issue(number, maturity, amount, status="미상환", kind="Corporate Bonds"):
    return {
        "rcept_no": number,
        "isu_cmpny": "삼성전자㈜",
        "scrits_knd_nm": kind,
        "isu_mth_nm": "Public offering",
        "isu_de": "2025.02.21",
        "facvalu_totamt": amount,
        "intrt": "3.36",
        "evl_grad_instt": "AA-(한국기업평가)",
        "mtd": maturity,
        "repy_at": status,
    }


def by_period(upstream, table):
    def answer(request):
        found = table.get((request.url.params["bsns_year"], request.url.params["reprt_code"]))
        return upstream.rows(*found) if found else upstream.status("013")

    return answer


def debt_record(upstream, *, major=(), offerings=()):
    """Serve periodic reports with debt tables, and an event index with the given filings."""
    reports = [
        filing(HALF_YEAR, "Semi-Annual Report (2026.06)"),
        filing(ANNUAL, "Annual Report (2025.12)"),
    ]
    groups = {"A": reports, "B": list(major), "C": list(offerings)}

    def index(request):
        found = groups[request.url.params.get("pblntf_ty", "A")]
        return upstream.rows(*found) if found else upstream.status("013")

    upstream.route("/company.json", upstream.ok(**profile()))
    upstream.route("/list.json", index)
    issues = {
        ("2026", "11012"): [
            issue(HALF_YEAR, "2026.12.04", "50,000,000,000", kind="Commercial Paper"),
            issue(HALF_YEAR, "2026.09.01", "20,000,000,000", kind="Commercial Paper"),
        ],
        ("2025", "11011"): [
            issue(ANNUAL, "2027.02.19", "150,000,000,000"),
            issue(ANNUAL, "2027.03.02", "143,490,000,000", status="일부상환"),
        ],
    }
    upstream.route("/detScritsIsuAcmslt.json", by_period(upstream, issues))
    balance = {
        "rcept_no": HALF_YEAR,
        "remndr_exprtn1": "Unredeemed balance",
        "remndr_exprtn2": "Total",
        "yy1_below": "803,572,000,000",
        "yy1_excess_yy2_below": "1,133,960,000,000",
        "sm": "1,937,532,000,000",
    }
    upstream.route("/cprndNrdmpBlce.json", by_period(upstream, {("2026", "11012"): [balance]}))


async def call(client, **arguments):
    result = await client.call_tool(
        "get_corporate_action_calendar",
        {"companies": ["005930"], "horizon": "6m", **arguments},
        raise_on_error=False,
    )
    return result, result.structured_content


def debt_rows(data):
    return [
        (i["date"], i["details"]["face_value"], i["details"].get("redeemed"))
        for i in data["items"]
        if i["action"] == "debt_maturity"
    ]


@pytest.mark.anyio
async def test_debt_maturities_come_with_coverage_and_ladder_notes(client, upstream):
    debt_record(upstream)
    result, data = await call(client)
    assert not result.is_error
    assert debt_rows(data) == [
        ("2026-12-04", 50_000_000_000, "no"),
        ("2027-02-19", 150_000_000_000, "no"),
        ("2027-03-02", 143_490_000_000, "partly"),
    ]
    first = data["items"][0]
    assert (first["source_kind"], first["filing_number"]) == ("debt_securities", HALF_YEAR)
    assert first["details"]["instrument"] == "Commercial Paper"
    assert COVERAGE in data["notes"]
    assert LADDER_NOTE in data["notes"]
    assert data["notes"][-1] == LADDER_NOTE
    assert [(p["bsns_year"], p["reprt_code"]) for p in upstream.params("/cprndNrdmpBlce.json")] == [
        ("2026", "11012")
    ]
    text = result.content[0].text
    assert "| Debt maturity | Debt maturity |" in text
    assert "face_value 143,490,000,000; coupon 3.36; redeemed partly" in text


@pytest.mark.anyio
async def test_include_past_reaches_back_for_maturities_too(client, upstream):
    debt_record(upstream)
    _, data = await call(client, include_past="60d", horizon="2026-12-31")
    assert [row[0] for row in debt_rows(data)] == ["2026-09-01", "2026-12-04"]


@pytest.mark.anyio
async def test_kinds_without_debt_maturity_read_no_debt_record(client, upstream):
    debt_record(upstream)
    upstream.records("/tsstkAqDecsn.json", buyback(company=("00126380", "SAMSUNG", "005930", "Y")))
    _, data = await call(client, kinds=["buyback"])
    assert {i["action"] for i in data["items"]} == {"buyback_end"}
    assert upstream.count("/detScritsIsuAcmslt.json") == 0
    assert upstream.count("/cprndNrdmpBlce.json") == 0
    assert COVERAGE not in data["notes"]


@pytest.mark.anyio
async def test_debt_maturity_alone_reads_no_event_reports(client, upstream):
    debt_record(upstream)
    _, data = await call(client, kinds=["debt_maturity"])
    assert {i["action"] for i in data["items"]} == {"debt_maturity"}
    assert {p.get("pblntf_ty") for p in upstream.params("/list.json")} == {"A"}
    assert not any(note.startswith("Dates come from") for note in data["notes"])


@pytest.mark.anyio
async def test_debt_maturity_with_kinds_without_dates(client, upstream):
    debt_record(upstream)
    result, data = await call(client, kinds=["lawsuit", "debt_maturity"])
    assert not result.is_error
    assert "Left out kinds without calendar dates: lawsuit." in data["notes"]
    assert upstream.count("/lwstLg.json") == 0
    unknown, _ = await call(client, kinds=["debt"])
    assert unknown.is_error
    assert "The calendar also accepts debt_maturity." in unknown.content[0].text


@pytest.mark.anyio
async def test_a_failed_debt_record_is_noted_while_events_answer(client, upstream):
    debt_record(upstream, major=[filing("20260901000456", "Decision on Merger")])
    upstream.records("/cmpMgDecsn.json", merger())
    upstream.route("/detScritsIsuAcmslt.json", upstream.status("800"))
    result, data = await call(client)
    assert not result.is_error
    assert {i["source_kind"] for i in data["items"]} == {"merger"}
    note = "Debt maturities unavailable for SAMSUNG ELECTRONICS CO,.LTD: OpenDART is under maintenance (status 800). Retry later."
    assert note in data["notes"]


@pytest.mark.anyio
async def test_a_debt_maturity_replaces_the_offering_statements_maturity(client, upstream):
    offering = filing("20250210000555", "Registration Statement (Debt Securities)")
    debt_record(upstream, offerings=[offering])
    general = {
        "rcept_no": "20250210000555",
        **identity(),
        "tm": "101",
        "fta": "150,000,000,000",
        "rpd": "2027.02.19",
        "sbd": "2025.02.19",
        "rpt_rcpn": "-",
    }
    upstream.records("/bdRs.json", group=[{"title": "General matters", "list": [general]}])
    _, data = await call(client)
    due = [i for i in data["items"] if i["date"] == "2027-02-19"]
    assert [(i["action"], i["details"].get("offering_filing")) for i in due] == [
        ("debt_maturity", "20250210000555")
    ]
    assert [p["bgn_de"] for p in upstream.params("/bdRs.json")] == ["20231022"]


@pytest.mark.anyio
async def test_an_exhausted_quota_in_the_debt_record_fails_the_calendar(client, upstream):
    debt_record(upstream, major=[filing("20260901000456", "Decision on Merger")])
    upstream.records("/cmpMgDecsn.json", merger())
    upstream.route("/cprndNrdmpBlce.json", upstream.status("020"))
    result, _ = await call(client)
    assert result.is_error
    assert "Retry after 00:00 KST" in result.content[0].text
