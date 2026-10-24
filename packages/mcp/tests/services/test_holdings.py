"""5% holder and insider reports: window filtering, bounds, counts, and field parsing."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from opendart_analysis.domain.dates import DateWindow
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.services.holdings import holding_activity

WINDOW = DateWindow(date(2026, 4, 25), date(2026, 10, 22))


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
        yield opened


def number(day, sequence):
    return f"{day:%Y%m%d}{sequence:06d}"


def insider(day, sequence=1, change="100", **fields):
    row = {
        "rcept_no": number(day, sequence),
        "rcept_dt": day.isoformat(),
        "corp_code": "00126380",
        "repror": f"Officer {sequence}",
        "isu_exctv_rgist_at": "Unregistered executive",
        "isu_exctv_ofcps": "상무 ",
        "isu_main_shrholdr": "-",
        "sp_stock_lmp_cnt": "1,000",
        "sp_stock_lmp_irds_cnt": change,
        "sp_stock_lmp_rate": "0.00",
        "sp_stock_lmp_irds_rate": "-0.00",
    }
    return row | fields


def major(day, sequence=1, change="1,000", **fields):
    row = {
        "rcept_no": number(day, sequence),
        "rcept_dt": day.isoformat(),
        "corp_code": "00126380",
        "report_tp": "General",
        "repror": "국민연금공단",
        "stkqy": "300,000",
        "stkqy_irds": change,
        "stkrt": "7.01",
        "stkrt_irds": "0.02",
        "ctr_stkqy": "-",
        "ctr_stkrt": "-",
        "report_resn": "- 보유주식수 변동\n- 단순투자 목적",
    }
    return row | fields


async def activity(state, window=WINDOW, *, detailed=False):
    company = await state.companies.resolve("00126380")
    return await holding_activity(state, company, window, detailed=detailed)


@pytest.mark.anyio
async def test_reports_are_bounded_newest_first_while_counts_cover_the_window(state, upstream):
    start = date(2026, 5, 1)
    rows = [insider(start + timedelta(days=i), i, "-50" if i % 3 else "200") for i in range(30)]
    old = [insider(date(2026, 4, 24), 99), insider(date(2025, 1, 2), 98)]
    upstream.records("/elestock.json", *old, *rows)
    result = await activity(state)
    assert len(result.insider) == 15
    assert result.insider[0].filing_number == number(start + timedelta(days=29), 29)
    assert result.insider[0].change_pct is None
    summary = result.insider_summary
    assert (summary.reports, summary.shown, summary.increases, summary.decreases) == (
        30,
        15,
        10,
        20,
    )
    assert summary.net_change == 10 * 200 - 20 * 50
    assert result.notes == [
        "Showing the 15 newest of 30 insider reports filed since 2026-04-25; narrow activity_window, or call search_filings with category insider_ownership_report to list them all."
    ]
    assert result.major == []
    assert result.major_summary.reports == 0


@pytest.mark.anyio
async def test_detailed_results_show_more_reports_with_every_field(state, upstream):
    start = date(2026, 5, 1)
    upstream.records("/elestock.json", *(insider(start + timedelta(days=i), i) for i in range(30)))
    upstream.records(
        "/majorstock.json",
        *(
            major(start + timedelta(days=i), i, ctr_stkqy="5,000", ctr_stkrt="0.10")
            for i in range(12)
        ),
    )
    result = await activity(state, detailed=True)
    assert len(result.insider) == 30
    assert result.insider[0].change_pct == 0.0
    assert len(result.major) == 12
    assert (result.major[0].contract_shares, result.major[0].contract_pct) == (5000, 0.1)
    assert result.notes == []


@pytest.mark.anyio
async def test_concise_5_percent_reports_are_bounded_at_ten(state, upstream):
    start = date(2026, 5, 1)
    upstream.records("/majorstock.json", *(major(start + timedelta(days=i), i) for i in range(12)))
    result = await activity(state)
    assert len(result.major) == 10
    assert result.major[0].contract_shares is None
    assert result.notes[0].startswith("Showing the 10 newest of 12 5% holder reports")
    assert "major_holding_report" in result.notes[0]


@pytest.mark.anyio
async def test_fields_are_parsed_and_translated(state, upstream):
    upstream.records(
        "/elestock.json",
        insider(
            date(2026, 6, 1), 1, isu_exctv_rgist_at="등기임원", isu_main_shrholdr="10%이상주주"
        ),
        insider(
            date(2026, 6, 2), 2, isu_exctv_rgist_at="비등기임원", isu_main_shrholdr="Other status"
        ),
        insider(date(2026, 6, 3), 3, isu_exctv_rgist_at="-", isu_exctv_ofcps="-", rcept_dt="-"),
        insider(date(2026, 6, 4), 4, rcept_no="2026060"),
        insider(date(2026, 6, 5), 5, rcept_no="-"),
    )
    upstream.records(
        "/majorstock.json", major(date(2026, 6, 1), stkqy_irds="-348,407", stkrt_irds="-0.00")
    )
    result = await activity(state)
    third, second, first = result.insider
    assert (first.is_registered_officer, first.major_shareholder) == (
        True,
        "Shareholders holding 10% or more",
    )
    assert first.position == "상무"
    assert (second.is_registered_officer, second.major_shareholder) == (False, "Other status")
    assert (third.is_registered_officer, third.position, third.filed) == (
        None,
        None,
        date(2026, 6, 3),
    )
    report = result.major[0]
    assert (report.change_in_shares, report.change_in_pct) == (-348_407, 0.0)
    assert str(report.change_in_pct) == "0.0"
    assert report.reason == "보유주식수 변동; 단순투자 목적"
    assert result.major_summary.decreases == 1


@pytest.mark.anyio
async def test_windows_beyond_two_years_warn_about_the_listing_horizon(state):
    result = await activity(state, DateWindow(date(2023, 1, 1), date(2026, 10, 22)))
    assert result.notes == [
        "OpenDART lists holding reports from about the last two years only; call search_filings with category major_holding_report or insider_ownership_report for older ones."
    ]
    assert result.insider == result.major == []
    assert result.insider_summary.net_change == 0
