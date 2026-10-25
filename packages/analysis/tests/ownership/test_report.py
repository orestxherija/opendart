"""The ownership workflow: period probing, minority fallback, control changes, and sources."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_analysis.domain.periods import PeriodRef, parse_periodic_title
from opendart_analysis.extracts import FilingSource
from opendart_analysis.ownership import control_changes, minority_holders, ownership_report
from opendart_analysis.reports import PeriodicReport, ResolvedPeriod
from packages.analysis.tests.capital.records import (
    ANNUAL,
    HALF,
    TODAY,
    Company,
    Row,
    Source,
    share_row,
)

FY2025, H1, Q1 = PeriodRef(2025, "FY"), PeriodRef(2026, "H1"), PeriodRef(2026, "Q1")


def holders(number, end_date="2026-06-30"):
    common = {"filing_number": number, "stock_knd": "보통주", "stlm_dt": end_date}
    return [
        Row(nm="-", **common),
        Row(
            nm="Parent Co",
            relate="최대주주 본인",
            trmend_posesn_stock_co="300",
            trmend_posesn_stock_qota_rt="30.00",
            **common,
        ),
        Row(
            nm="Total", trmend_posesn_stock_co="300", trmend_posesn_stock_qota_rt="30.00", **common
        ),
    ]


def minority(number):
    return [
        Row(shrholdr_co="-", hold_stock_co="-", stlm_dt="2025-12-31", filing_number=number),
        Row(
            shrholdr_co="9,000",
            hold_stock_co="500",
            hold_stock_rate="50.00%",
            stlm_dt="2025-12-31",
            filing_number=number,
        ),
    ]


def half_year_report():
    title = "Semi-Annual Report (2026.06)"
    parsed = parse_periodic_title(title)
    assert parsed is not None
    return PeriodicReport(H1, parsed, HALF, title, date(2026, 8, 14))


async def read(resolved, *, largest, shares=None, changes=None, minorities=None):
    return await ownership_report(
        Company(),
        resolved,
        fetch_largest_holders=largest,
        fetch_share_counts=shares or Source(),
        fetch_control_changes=changes or Source(),
        fetch_minority_holders=minorities or Source(),
        today=TODAY,
    )


@pytest.mark.anyio
async def test_half_year_snapshots_take_minority_figures_from_the_annual_report():
    minorities = Source({(2025, "11011"): minority(ANNUAL)})
    shares = Source({(2026, "11012"): [share_row("보통주", *["-"] * 7, "1,000", "100", "900")]})
    report = await read(
        ResolvedPeriod((H1, Q1), half_year_report(), None),
        largest=Source({(2026, "11012"): holders(HALF)}),
        shares=shares,
        minorities=minorities,
    )
    assert report is not None
    assert (report.ref, report.period_end, report.minority_ref) == (H1, date(2026, 6, 30), FY2025)
    snapshot = report.snapshot
    assert snapshot.minority is not None
    assert (snapshot.minority.holders, snapshot.minority.share_pct) == (9000, 50.0)
    assert (snapshot.shares_issued, snapshot.free_float_estimate_pct) == (1000, 60.0)
    assert report.shares is not None
    assert report.sources == (
        FilingSource(HALF, "Semi-Annual Report (2026.06)"),
        FilingSource(ANNUAL, None),
    )
    assert report.notes == (
        "Minority shareholder figures come from the FY2025 annual report; quarterly and half-year reports usually omit them.",
    )
    assert [(q.fiscal_year, q.report_code, v) for q, v in minorities.queries] == [
        (2026, "11012", "low"),
        (2025, "11011", "low"),
    ]


@pytest.mark.anyio
async def test_a_report_without_tables_yet_falls_back_to_the_next_candidate():
    q1 = "20260515000456"
    largest = Source({(2026, "11013"): holders(q1, "2026-03-31")})
    report = await read(
        ResolvedPeriod((H1, Q1, FY2025), half_year_report(), None),
        largest=largest,
        minorities=Source({(2025, "11011"): minority(q1)}),
    )
    assert report is not None
    assert report.ref == Q1
    assert report.notes[0] == "The H1 2026 report has no ownership tables yet; showing Q1 2026."
    assert report.sources == (FilingSource(q1, None),)
    assert [(q.fiscal_year, q.report_code) for q, _ in largest.queries] == [
        (2026, "11012"),
        (2026, "11013"),
    ]


@pytest.mark.anyio
async def test_annual_snapshots_without_minority_figures_do_not_fall_back():
    minorities = Source()
    report = await read(
        ResolvedPeriod((FY2025,), None, None),
        largest=Source({(2025, "11011"): holders("2026031", "2025-12-31")}),
        minorities=minorities,
    )
    assert report is not None
    assert report.snapshot.minority is None
    assert report.minority_ref is None
    assert report.sources == ()
    assert report.notes == ()
    assert len(minorities.queries) == 1


@pytest.mark.anyio
async def test_no_named_holders_in_three_candidates_is_none():
    largest = Source({None: [Row(nm="-")]})
    refs = (PeriodRef(2026, "Q3"), H1, Q1, FY2025)
    assert await read(ResolvedPeriod(refs, None, None), largest=largest) is None
    assert len(largest.queries) == 3
    assert largest.queries[0][1] == "high"


def test_control_changes_are_parsed_newest_first_without_rows_of_dashes():
    dashes = {"posesn_stock_co": "-", "qota_rt": "-", "change_cause": "-", "rm": "-"}
    rows = [
        Row(change_on="-", mxmm_shrholdr_nm="-", **dashes),
        Row(change_on="2021.04.29", mxmm_shrholdr_nm="Heir", qota_rt="10.5", rm="비고"),
        Row(change_on="2023.06.01", mxmm_shrholdr_nm="Holding Co", posesn_stock_co="2,000"),
        Row(change_on="-", mxmm_shrholdr_nm="Undated", **dashes),
        Row(change_on="-", mxmm_shrholdr_nm="-", **(dashes | {"rm": "Only a note"})),
    ]
    changes = control_changes(rows)
    assert [(c.new_largest_shareholder, c.note) for c in changes] == [
        ("Holding Co", None),
        ("Heir", "비고"),
        ("Undated", None),
        (None, "Only a note"),
    ]
    assert (changes[0].date, changes[0].shares, changes[1].pct) == (date(2023, 6, 1), 2000, 10.5)


def test_minority_figures_come_from_the_first_row_with_values():
    found = minority_holders(minority(ANNUAL))
    assert found is not None
    figures, number = found
    assert (figures.holders, figures.shares, figures.as_of, number) == (
        9000,
        500,
        date(2025, 12, 31),
        ANNUAL,
    )
    assert minority_holders(minority(ANNUAL)[:1]) is None
