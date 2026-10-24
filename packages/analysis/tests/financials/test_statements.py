"""Financial-statement building blocks: vocabulary, period layout, merging, and derived metrics."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_analysis.documents.preliminary import PreliminaryEarnings, PreliminaryPeriod
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.financials import accounts, derived, statements
from opendart_analysis.financials.chain import fallback_note
from opendart_analysis.financials.quarters import quarter, quarter_lines, quarters

FY25 = PeriodRef(2025, "FY", end_date=date(2025, 12, 31))
H126 = PeriodRef(2026, "H1", end_date=date(2026, 6, 30))


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (None, None),
        ("-", None),
        ("자본 [구성요소]", "Total"),
        ("별도재무제표 [member]", "Total"),
        ("자본의 구성요소 [도메인]|지배기업 소유주지분|자본금", "Issued capital"),
        ("자본 [구성요소]|비지배지분 [구성요소]", "Non-controlling interests"),
        ("자본 [구성요소]|기타포괄손익누계액 [구성요소]", "Other components of equity"),
        ("자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]", "Owners of the parent"),
        ("Equity [member]|Retained earnings [member]", "Retained earnings"),
        ("자본 [구성요소]|전환권대가 [구성요소]", "전환권대가"),
    ],
)
def test_equity_components_are_named_from_the_member_path(detail, expected):
    assert accounts.component(detail) == expected


def test_account_vocabulary_matches_ids_and_names():
    assert accounts.normalize("Profit(loss) before income tax") == "profitbeforeincometax"
    assert accounts.standard_id("-Standard account code not used-") is None
    assert accounts.standard_id(" ifrs-full_Revenue ") == "ifrs-full_Revenue"
    assert accounts.standard_id(None) is None
    assert accounts.metric_of(None, "Sales").key == "revenue"
    assert accounts.metric_of(None, "매출액").key == "revenue"
    assert accounts.metric_of("ifrs-full_Assets", "Whatever").key == "total_assets"
    assert accounts.metric_of(None, "Gross profit") is None
    assert accounts.is_per_share("ifrs-full_DilutedEarningsLossPerShare", "x")
    assert accounts.is_per_share(None, "Dividends per share")
    assert not accounts.is_per_share(None, "Revenue")


def test_layouts_follow_the_report_period():
    assert [r.label for r in statements.layout(FY25, "IS")] == ["FY2025", "FY2024", "FY2023"]
    balance = statements.layout(H126, "BS")
    assert [(r.label, r.end_date) for r in balance] == [
        ("H1 2026", date(2026, 6, 30)),
        ("FY2025", date(2025, 12, 31)),
    ]
    income = statements.layout(H126, "IS")
    assert income[1] == PeriodRef(2025, "H1")
    assert income[1].end_date == date(2025, 6, 30)
    assert statements.shift(PeriodRef(2025, "Q3"), 1).end_date is None
    assert statements.prior_year_end(PeriodRef(2025, "Q1")).end_date is None


def test_numbers_keep_integers_exact():
    assert statements.number("6,600") == 6600
    assert statements.number("1,234.5") == 1234.5
    assert statements.number("-") is None
    assert statements.number("#########") is None


def item(account, amounts, *, statement="IS", account_id=None, cumulative=(None, None)):
    return statements.Item(
        statement, account, account_id, None, amounts, cumulative, "20260310002820", "KRW"
    )


def test_reports_drop_exact_duplicates_and_number_repeated_names():
    rows = [
        item("Profit", ("1", "2", "3")),
        item("Profit(loss)", ("1", "2", "3")),
        item("Other", ("4", "5", "6")),
        item("Other", ("7", "8", "9")),
        item("Other", ("1", "1", "1")),
    ]
    report = statements.build_report(rows, FY25, rank=lambda _, position: position)
    assert [line.key for line in report.lines] == [
        "IS:profit",
        "IS:other",
        "IS:other#2",
        "IS:other#3",
    ]
    assert report.filings == ("20260310002820",)
    assert statements.build_report([], FY25, rank=lambda _, p: p).currency == "KRW"


def test_merging_keeps_newer_values_and_fills_gaps():
    newer = statements.build_report(
        [item("Revenue", ("10", None, "8"), cumulative=("20", None))], H126, rank=lambda _, p: p
    )
    older = statements.build_report(
        [
            item("Revenue", ("9", "7", None), cumulative=("19", "15")),
            item("Gross profit", ("5", "4", None)),
        ],
        PeriodRef(2025, "H1", end_date=date(2025, 6, 30)),
        rank=lambda _, p: p,
    )
    merged = statements.merge([newer, older])
    revenue, gross = merged.lines
    assert revenue.values == {H126: 10, PeriodRef(2025, "H1"): 9, PeriodRef(2024, "H1"): 7}
    assert revenue.cumulative == {H126: 20, PeriodRef(2025, "H1"): 19, PeriodRef(2024, "H1"): 15}
    assert gross.account == "Gross profit"
    assert [ref.label for ref in statements.filled_periods(merged.lines)] == [
        "H1 2026",
        "H1 2025",
        "H1 2024",
    ]
    assert newer.lines[0].values == {H126: 10, PeriodRef(2025, "H1"): None}


def test_derived_metrics_need_positive_bases():
    values = {
        "revenue": (100, -50),
        "operating_income": (10, 0),
        "net_income": (None, 5),
        "total_liabilities": (30, None),
        "total_equity": (-1, None),
        "current_assets": (5, None),
        "current_liabilities": (0, None),
    }
    assert derived.compute(values) == {"operating_margin": 10.0}
    assert derived.note([], period="FY2025", comparison="FY2024") is None
    assert derived.note(["revenue_growth"], period="FY2025", comparison=None).endswith(
        "revenue_growth = change versus None."
    )
    line = statements.Line("k", "Revenue", None, None, 0, {FY25: 5}, name="Revenue")
    assert derived.metric_values([line], FY25, None) == {"revenue": (5, None)}


def test_fallback_notes_name_the_period_without_data():
    assert fallback_note([], FY25) is None
    assert fallback_note([FY25], FY25) is None
    assert (
        fallback_note([H126, FY25], FY25) == "OpenDART has no data for H1 2026 yet; showing FY2025."
    )


def test_quarters_are_labeled_by_fiscal_year_end():
    march = quarter(date(2025, 6, 30), fye_month=3)
    assert (march.label, march.ref.period, march.ref.fiscal_year) == ("Q1 2026", "Q1", 2026)
    fourth = quarter(date(2025, 12, 31), fye_month=12)
    assert (fourth.label, fourth.ref.period) == ("Q4 2025", "FY")
    earnings = PreliminaryEarnings(
        filing_number="1",
        basis="separate",
        periods=[PreliminaryPeriod(key="current_quarter", label_ko="x", end="2026-03-31")],
        rows=[],
        is_amendment=False,
    )
    assert [q.label for q in quarters(earnings, fye_month=12)] == ["Q1 2026", "Q4 2025", "Q1 2025"]
    laid = quarter_lines(earnings, fye_month=12)
    assert (laid.lines, laid.derived, laid.formula) == ((), {}, None)
    undated = earnings.model_copy(update={"periods": []})
    assert quarter_lines(undated, fye_month=12) is None
