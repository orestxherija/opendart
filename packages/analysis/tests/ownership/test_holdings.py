"""5% holder and insider reports: window filtering, ordering, counts, and field parsing."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from opendart_analysis.ownership import (
    LISTING_MONTHS,
    activity,
    holding_reports,
    predates_listings,
)
from packages.analysis.tests.capital.records import TODAY, Row, Source

SINCE = date(2026, 4, 25)


def number(day, sequence):
    return f"{day:%Y%m%d}{sequence:06d}"


def insider(day, sequence=1, change="100", **fields):
    row = {
        "filing_number": number(day, sequence),
        "filing_date": day.isoformat(),
        "repror": f"Officer {sequence}",
        "isu_exctv_rgist_at": "Unregistered executive",
        "isu_exctv_ofcps": "상무 ",
        "isu_main_shrholdr": "-",
        "sp_stock_lmp_cnt": "1,000",
        "sp_stock_lmp_irds_cnt": change,
        "sp_stock_lmp_rate": "0.00",
        "sp_stock_lmp_irds_rate": "-0.00",
    }
    return Row(**(row | fields))


def major(day, sequence=1, change="1,000", **fields):
    row = {
        "filing_number": number(day, sequence),
        "filing_date": day.isoformat(),
        "report_tp": "General",
        "repror": "국민연금공단",
        "stkqy": "300,000",
        "stkqy_irds": change,
        "stkrt": "7.01",
        "stkrt_irds": "-0.00",
        "ctr_stkqy": "5,000",
        "ctr_stkrt": "0.10",
        "report_resn": "- 보유주식수 변동\n- 단순투자 목적",
    }
    return Row(**(row | fields))


async def read(majors=(), insiders=(), since=SINCE):
    major_source, insider_source = Source({None: list(majors)}), Source({None: list(insiders)})
    reports = await holding_reports(
        "00126380",
        since=since,
        fetch_major_holdings=major_source,
        fetch_insider_holdings=insider_source,
        today=TODAY,
    )
    return reports, major_source, insider_source


@pytest.mark.anyio
async def test_reports_in_the_window_come_newest_first_with_counts():
    start = date(2026, 5, 1)
    rows = [insider(start + timedelta(days=i), i, "-50" if i % 3 else "200") for i in range(30)]
    old = [insider(date(2026, 4, 24), 99), insider(date(2025, 1, 2), 98)]
    reports, major_source, insider_source = await read(insiders=[*old, *rows])
    assert (reports.since, reports.until) == (SINCE, TODAY)
    assert len(reports.insider) == 30
    assert reports.insider[0].filing_number == number(start + timedelta(days=29), 29)
    assert reports.insider_activity == activity([200] * 10 + [-50] * 20)
    assert (reports.insider_activity.increases, reports.insider_activity.decreases) == (10, 20)
    assert reports.insider_activity.net_change == 10 * 200 - 20 * 50
    assert reports.major == ()
    assert reports.major_activity.reports == 0
    ((query, volatility),) = major_source.queries
    assert (query.corp_code, volatility) == ("00126380", "medium")
    assert insider_source.queries == major_source.queries


@pytest.mark.anyio
async def test_fields_are_parsed_and_translated():
    insiders = [
        insider(
            date(2026, 6, 1), 1, isu_exctv_rgist_at="등기임원", isu_main_shrholdr="10%이상주주"
        ),
        insider(
            date(2026, 6, 2), 2, isu_exctv_rgist_at="비등기임원", isu_main_shrholdr="Other status"
        ),
        insider(date(2026, 6, 3), 3, isu_exctv_rgist_at="-", isu_exctv_ofcps="-", filing_date="-"),
        insider(date(2026, 6, 4), 4, filing_number="2026060"),
        insider(date(2026, 6, 5), 5, filing_number="-"),
    ]
    majors = [major(date(2026, 6, 1), stkqy_irds="-348,407")]
    reports, _, _ = await read(majors, insiders)
    third, second, first = reports.insider
    assert (first.is_registered_officer, first.major_shareholder, first.position) == (
        True,
        "Shareholders holding 10% or more",
        "상무",
    )
    assert first.change_pct == 0.0
    assert str(first.change_pct) == "0.0"
    assert (second.is_registered_officer, second.major_shareholder) == (False, "Other status")
    assert (third.is_registered_officer, third.position, third.filed) == (
        None,
        None,
        date(2026, 6, 3),
    )
    (report,) = reports.major
    assert (report.change_in_shares, report.change_in_pct) == (-348_407, 0.0)
    assert (report.contract_shares, report.contract_pct) == (5000, 0.1)
    assert report.reason == "보유주식수 변동; 단순투자 목적"
    assert reports.major_activity == activity([-348_407])


@pytest.mark.anyio
async def test_windows_must_not_start_after_today():
    with pytest.raises(ValueError, match="after today"):
        await read(since=TODAY + timedelta(days=1))


def test_listings_reach_about_two_years_back():
    assert LISTING_MONTHS == 24
    assert not predates_listings(date(2024, 10, 22), TODAY)
    assert predates_listings(date(2024, 10, 21), TODAY)


def test_activity_counts_ignore_unknown_and_zero_changes():
    counts = activity([None, 0, 5, -2])
    assert (counts.reports, counts.increases, counts.decreases, counts.net_change) == (4, 1, 1, 3)
