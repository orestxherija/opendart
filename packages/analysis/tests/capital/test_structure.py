"""Capital structure: treasury stock, capital changes, use of proceeds, and the workflow."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_analysis.capital import (
    SECTIONS,
    capital_changes,
    capital_structure,
    change_category,
    proceeds_uses,
    treasury_methods,
    treasury_totals,
)
from opendart_analysis.domain.periods import PeriodRef, parse_periodic_title
from opendart_analysis.errors import NotConfiguredError
from opendart_analysis.extracts import FilingSource
from opendart_analysis.reports import PeriodicReport, ResolvedPeriod
from packages.analysis.tests.capital.records import ANNUAL, TODAY, Company, Row, Source, share_row

FY2025 = PeriodRef(2025, "FY")
MOVES = ("stock_knd", "acqs_mth1", "acqs_mth2", "acqs_mth3", "bsis_qy", "change_qy_acqs")
MOVES += ("change_qy_dsps", "change_qy_incnr", "trmend_qy")
SHARES = share_row("보통주", "-", "-", "-", "-", "-", "-", "-", "1,000", "10", "990")
DIVIDEND = "배당가능이익 범위 이내 취득"


def treasury(*values, rm="-"):
    return Row(rm=rm, **dict(zip(MOVES, values, strict=True)))


METHODS = [
    treasury(
        "보통주", DIVIDEND, "직접 취득", "장내 직접 취득", "10", "5", "-", "2", "13", rm="소각"
    ),
    treasury(
        "보통주", DIVIDEND, "신탁계약에 의한 취득", "수탁자 보유물량", "1", "1", "1", "-", "1"
    ),
    treasury("보통주", DIVIDEND, "직접 취득", "소계", "10", "5", "-", "2", "13"),
    treasury("우선주", "기타 취득", "기타 취득", "기타 취득", "-", "3", "-", "-", "3"),
    treasury("우선주", "기타 취득", "기타 취득", "기타 취득", "-", "-", "-", "-", "-"),
]


@pytest.mark.parametrize(
    ("kind", "category"),
    [
        ("유상증자(주주배정)", "paid-in capital increase (shareholder allotment)"),
        (
            "유상증자(주주배정후 실권주 일반공모)",
            "paid-in capital increase (shareholder allotment)",
        ),
        (
            "유상증자(주주우선공모)",
            "paid-in capital increase (shareholder-priority public offering)",
        ),
        ("유상증자", "paid-in capital increase"),
        ("무상증자", "bonus issue"),
        ("주식배당", "stock dividend"),
        ("전환권행사", "conversion"),
        ("신주인수권행사", "warrant exercise"),
        ("주식매수선택권행사", "stock option exercise"),
        ("무상감자", "capital reduction"),
        ("이익소각", "share retirement"),
        ("합병", "merger"),
        ("액면분할", "stock split"),
        ("주식병합", "share consolidation"),
        ("주식교환", "share exchange"),
        ("상환우선주 상환", "redemption"),
        ("기타", None),
        (None, None),
    ],
)
def test_change_types_are_named_in_english(kind, category):
    assert change_category(kind) == category


def test_treasury_totals_are_added_up_when_no_total_rows_are_filed():
    totals = [
        (r.share_class, r.method, r.begin, r.acquired, r.end) for r in treasury_totals(METHODS)
    ]
    assert totals == [("common", None, 11, 6, 14), ("preferred", None, None, 3, 3)]
    methods = treasury_methods(METHODS)
    assert [m.method for m in methods] == [
        f"{DIVIDEND} > 직접 취득 > 장내 직접 취득",
        f"{DIVIDEND} > 신탁계약에 의한 취득 > 수탁자 보유물량",
        "기타 취득",
    ]
    assert methods[0].note == "소각"


def test_filed_total_rows_win_and_keep_their_note():
    total = treasury("보통주", "Total", "Total", "Total", "20", "-", "-", "-", "20", rm="비고")
    empty = treasury("우선주", "합계", "-", "-", "-", "-", "-", "-", "-")
    (row,) = treasury_totals([*METHODS, total, empty])
    assert (row.share_class, row.method, row.begin, row.end, row.note) == (
        "common",
        None,
        20,
        20,
        "비고",
    )


def test_changes_without_dates_or_counts_are_dropped_and_dated_ones_come_first():
    rows = [
        Row(isu_dcrs_de="-", isu_dcrs_stle="해당사항 없음", isu_dcrs_qy="-"),
        Row(
            isu_dcrs_de="-",
            isu_dcrs_stle="전환권행사",
            isu_dcrs_stock_knd="보통주",
            isu_dcrs_qy="500",
        ),
        Row(
            isu_dcrs_de="2020.01.02",
            isu_dcrs_stle="무상증자",
            isu_dcrs_stock_knd="보통주",
            isu_dcrs_qy="100",
            isu_dcrs_mstvdv_fval_amount="100",
        ),
    ]
    changes = capital_changes(rows)
    assert [(c.date, c.category, c.shares, c.par_value) for c in changes] == [
        (date(2020, 1, 2), "bonus issue", 100, 100),
        (None, "conversion", 500, None),
    ]


def test_proceeds_list_public_offerings_first_without_rows_of_dashes():
    public = [
        Row(se_nm="유상증자", tm="1", pay_de="2025.05.30", rs_cptal_use_plan_useprps="시설자금")
    ]
    private = [
        Row(se_nm="해당사항 없음", tm="-", pay_de="-", pay_amount="-"),
        Row(se_nm="전환사채", tm="3", pay_amount="5,000,000,000", cptal_use_plan="운영자금"),
    ]
    first, second = proceeds_uses(public, private)
    assert (first.offering, first.series, first.paid_on, first.planned_use) == (
        "public",
        "1",
        date(2025, 5, 30),
        "시설자금",
    )
    assert (second.offering, second.amount_paid, second.plan) == (
        "private",
        5_000_000_000,
        "운영자금",
    )


def resolved(*refs, report=None, note=None):
    return ResolvedPeriod(refs or (FY2025,), report, note)


def annual_report():
    title = "Annual Report (2025.12)"
    parsed = parse_periodic_title(title)
    assert parsed is not None
    return PeriodicReport(FY2025, parsed, ANNUAL, title, date(2026, 3, 10))


@pytest.mark.anyio
async def test_every_section_is_read_for_the_period_with_share_counts():
    shares, moves = Source({(2025, "11011"): [SHARES]}), Source({None: METHODS})
    changes, public, private = Source(), Source(), Source()
    messages = []

    async def progress(message):
        messages.append(message)

    structure = await capital_structure(
        Company(),
        resolved(report=annual_report()),
        fetch_share_counts=shares,
        fetch_treasury_stock=moves,
        fetch_capital_changes=changes,
        fetch_public_proceeds=public,
        fetch_private_proceeds=private,
        today=TODAY,
        progress=progress,
    )
    assert structure is not None
    assert structure.sections == SECTIONS
    assert (structure.ref, structure.period_end) == (FY2025, date(2025, 12, 31))
    assert structure.shares.outstanding == 990
    assert structure.treasury_stock is not None
    assert len(structure.treasury_stock) == 2
    assert structure.treasury_stock_by_method is not None
    assert len(structure.treasury_stock_by_method) == 3
    assert structure.capital_changes == structure.use_of_proceeds == ()
    assert structure.sources == (FilingSource(ANNUAL, "Annual Report (2025.12)"),)
    assert structure.notes == ()
    assert messages == ["Reading the FY2025 capital tables"]
    for source in (moves, changes, public, private):
        ((query, volatility),) = source.queries
        assert (query.fiscal_year, query.report_code, volatility) == (2025, "11011", "low")


@pytest.mark.anyio
async def test_unrequested_sections_are_neither_read_nor_needed():
    shares = Source({(2025, "11011"): [SHARES]})
    structure = await capital_structure(
        Company(), resolved(), sections=["shares"], fetch_share_counts=shares, today=TODAY
    )
    assert structure is not None
    assert structure.sections == ("shares",)
    assert structure.treasury_stock is structure.treasury_stock_by_method is None
    assert structure.capital_changes is structure.use_of_proceeds is None
    assert structure.sources == (FilingSource(ANNUAL, None),)


@pytest.mark.anyio
async def test_requested_sections_need_their_data_access():
    shares = Source({(2025, "11011"): [SHARES]})
    with pytest.raises(NotConfiguredError) as raised:
        await capital_structure(
            Company(),
            resolved(),
            sections=["use_of_proceeds"],
            fetch_share_counts=shares,
            fetch_public_proceeds=Source(),
            today=TODAY,
        )
    assert raised.value.dependency == "fetch_private_proceeds"
    assert shares.queries == []


@pytest.mark.anyio
async def test_a_later_candidate_is_explained_and_no_table_is_none():
    q1 = PeriodRef(2026, "Q1")
    shares = Source({(2026, "11013"): [share_row("보통주", *["-"] * 9, "5", number="2026051")]})
    structure = await capital_structure(
        Company(),
        resolved(PeriodRef(2026, "H1"), q1),
        sections=["shares"],
        fetch_share_counts=shares,
        today=TODAY,
    )
    assert structure is not None
    # A period without a known end date takes the table's settlement date.
    assert structure.period_end == date(2025, 12, 31)
    assert structure.notes == ("The H1 2026 report has no share-count table yet; showing Q1 2026.",)
    assert structure.sources == ()
    missing = await capital_structure(
        Company(), resolved(), sections=["shares"], fetch_share_counts=Source(), today=TODAY
    )
    assert missing is None
