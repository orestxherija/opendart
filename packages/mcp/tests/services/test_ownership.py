"""get_ownership orchestration: period fallbacks, minority fallback, control changes, sources."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.services.ownership import OwnershipQuery, activity_window, ownership

H1_REPORT, FY_REPORT = "20260814001234", "20260310002820"
TODAY = date(2026, 10, 22)


@pytest.fixture
async def state(mcp_settings, sdk_settings, upstream, now):
    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/company.json", upstream.ok(corp_name="삼성전자", corp_cls="Y", acc_mt="12"))
    async with open_state(
        mcp_settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as opened:
        # Wait for the directory so company identity does not depend on load timing.
        await opened.directory.wait(5)
        yield opened


def by_period(upstream, table):
    """Answer a periodic-report endpoint by (bsns_year, reprt_code); 013 otherwise."""

    def route(request):
        key = (request.url.params["bsns_year"], request.url.params["reprt_code"])
        rows = table.get(key)
        return upstream.rows(*rows) if rows else upstream.status("013")

    return route


def holders(number, end_date):
    common = {"rcept_no": number, "stock_knd": "보통주", "stlm_dt": end_date}
    return (
        common
        | {
            "nm": "Parent Co",
            "relate": "최대주주 본인",
            "trmend_posesn_stock_co": "300",
            "trmend_posesn_stock_qota_rt": "30.00",
        },
        common
        | {"nm": "Total", "trmend_posesn_stock_co": "300", "trmend_posesn_stock_qota_rt": "30.00"},
    )


def minority(number):
    return (
        {
            "rcept_no": number,
            "se": "소액주주",
            "shrholdr_co": "9,000",
            "hold_stock_co": "500",
            "hold_stock_rate": "50.00%",
            "stlm_dt": "2025-12-31",
        },
    )


def latest(upstream, number, title):
    upstream.records(
        "/list.json",
        {"corp_code": "00126380", "report_nm": title, "rcept_no": number, "rcept_dt": number[:8]},
    )


async def run(state, **arguments):
    return await ownership(state, OwnershipQuery(company="00126380", **arguments))


@pytest.mark.anyio
async def test_half_year_snapshots_take_minority_figures_from_the_annual_report(state, upstream):
    latest(upstream, H1_REPORT, "Semi-Annual Report (2026.06)")
    upstream.route(
        "/hyslrSttus.json",
        by_period(upstream, {("2026", "11012"): holders(H1_REPORT, "2026-06-30")}),
    )
    upstream.route("/mrhlSttus.json", by_period(upstream, {("2025", "11011"): minority(FY_REPORT)}))
    result = await run(state)
    assert (result.fiscal_year, result.period, result.period_end) == (2026, "H1", date(2026, 6, 30))
    assert result.snapshot is not None
    assert result.snapshot.minority is not None
    assert (result.snapshot.minority.holders, result.snapshot.minority.share_pct) == (9000, 50.0)
    assert result.snapshot.minority.as_of == date(2025, 12, 31)
    assert [source.filing_number for source in result.source_filings] == [H1_REPORT, FY_REPORT]
    assert result.source_filings[0].title == "Semi-Annual Report (2026.06)"
    assert result.source_filings[1].title is None
    assert (
        "Minority shareholder figures come from the FY2025 annual report; quarterly and half-year reports usually omit them."
        in result.notes
    )
    params = upstream.params("/mrhlSttus.json")
    assert [(p["bsns_year"], p["reprt_code"]) for p in params] == [
        ("2026", "11012"),
        ("2025", "11011"),
    ]


@pytest.mark.anyio
async def test_a_report_without_tables_yet_falls_back_to_the_next_candidate(state, upstream):
    latest(upstream, H1_REPORT, "Semi-Annual Report (2026.06)")
    q1 = "20260515000456"
    upstream.route(
        "/hyslrSttus.json", by_period(upstream, {("2026", "11013"): holders(q1, "2026-03-31")})
    )
    upstream.route("/mrhlSttus.json", by_period(upstream, {("2025", "11011"): minority(q1)}))
    result = await run(state)
    assert (result.fiscal_year, result.period) == (2026, "Q1")
    assert "The H1 2026 report has no ownership tables yet; showing Q1 2026." in result.notes
    assert [source.filing_number for source in result.source_filings] == [q1]
    assert result.source_filings[0].title is None
    tried = [(p["bsns_year"], p["reprt_code"]) for p in upstream.params("/hyslrSttus.json")]
    # Q3 2026 ends after the latest filed report, so it is not probed.
    assert tried == [("2026", "11012"), ("2026", "11013")]


@pytest.mark.anyio
async def test_annual_snapshots_without_minority_figures_do_not_fall_back(state, upstream):
    upstream.route(
        "/hyslrSttus.json",
        by_period(upstream, {("2025", "11011"): holders("2026031", "2025-12-31")}),
    )
    result = await run(state, period="FY", fiscal_year=2025)
    assert result.snapshot is not None
    assert result.snapshot.minority is None
    assert result.source_filings == []
    assert result.period_end == date(2025, 12, 31)
    assert upstream.count("/mrhlSttus.json") == 1
    assert not any(note.startswith("Minority") for note in result.notes)


@pytest.mark.anyio
async def test_control_changes_are_parsed_newest_first(state, upstream):
    upstream.route(
        "/hyslrSttus.json",
        by_period(upstream, {("2025", "11011"): holders(FY_REPORT, "2025-12-31")}),
    )
    changes = [
        {
            "change_on": "-",
            "mxmm_shrholdr_nm": "-",
            "posesn_stock_co": "-",
            "qota_rt": "-",
            "change_cause": "-",
            "rm": "-",
        },
        {
            "change_on": "2021.04.29",
            "mxmm_shrholdr_nm": "Heir",
            "posesn_stock_co": "1,000",
            "qota_rt": "10.5",
            "change_cause": "상속",
            "rm": "비고",
        },
        {
            "change_on": "2023.06.01",
            "mxmm_shrholdr_nm": "Holding Co",
            "posesn_stock_co": "2,000",
            "qota_rt": "21.00",
            "change_cause": "지주회사 전환",
            "rm": "-",
        },
        {
            "change_on": "-",
            "mxmm_shrholdr_nm": "Undated",
            "posesn_stock_co": "-",
            "qota_rt": "-",
            "change_cause": "-",
            "rm": "-",
        },
    ]
    upstream.records("/hyslrChgSttus.json", *changes)
    concise = await run(state, period="FY", fiscal_year=2025)
    assert [c.new_largest_shareholder for c in concise.control_changes] == [
        "Holding Co",
        "Heir",
        "Undated",
    ]
    assert concise.control_changes[0].date == date(2023, 6, 1)
    assert concise.control_changes[1].note is None
    detailed = await run(state, period="FY", fiscal_year=2025, detailed=True)
    assert detailed.control_changes[1].note == "비고"
    assert detailed.control_changes[1].pct == 10.5


@pytest.mark.anyio
async def test_minority_figures_from_the_same_report_are_cited_once(state, upstream):
    latest(upstream, H1_REPORT, "Semi-Annual Report (2026.06)")
    upstream.route(
        "/hyslrSttus.json",
        by_period(upstream, {("2026", "11012"): holders(H1_REPORT, "2026-06-30")}),
    )
    upstream.route("/mrhlSttus.json", by_period(upstream, {("2025", "11011"): minority(H1_REPORT)}))
    result = await run(state)
    assert [source.filing_number for source in result.source_filings] == [H1_REPORT]


@pytest.mark.parametrize(
    ("text", "start"),
    [
        ("180d", date(2026, 4, 25)),
        ("2026-01-01", date(2026, 1, 1)),
        ("today", TODAY),
        ("ytd", date(2026, 1, 1)),
    ],
)
def test_activity_windows_end_today(text, start):
    window = activity_window(text, TODAY)
    assert (window.start, window.end) == (start, TODAY)


@pytest.mark.parametrize("text", ["soon", "2026-13-01", "2026-10-23", "-5d"])
def test_unusable_activity_windows_raise(text):
    with pytest.raises(InvalidArgumentError, match="activity_window"):
        activity_window(text, TODAY)
