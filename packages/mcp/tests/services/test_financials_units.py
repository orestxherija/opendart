"""Unit tests for the financial-statement building blocks, without the MCP protocol."""

from __future__ import annotations

from datetime import date

import pytest

from opendart.models.financial_statements import (
    FnlttMultiAcntResponseListItem,
    FnlttSinglAcntAllResponseListItem,
)
from opendart_analysis.documents.preliminary import PreliminaryEarnings, PreliminaryPeriod
from opendart_analysis.domain.periods import PeriodRef
from opendart_mcp.core.errors import UpstreamError
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.financials import EquityInvestment
from opendart_mcp.models.preliminary import PreliminaryResult
from opendart_mcp.services import accounts, derived, statement_views, statements
from opendart_mcp.services.compare import _owner
from opendart_mcp.services.fanout import gather
from opendart_mcp.services.investments import Holdings, holdings_table
from opendart_mcp.services.preliminary_table import preliminary_table, quarter, quarters
from opendart_mcp.services.tables import fallback_note, no_data, sources

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
    assert statements.column(PeriodRef(2025, "Q3"), fye_month=12).end_date == date(2025, 9, 30)


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
    assert report.filings == ["20260310002820"]
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


def test_concise_selection_falls_back_when_few_key_lines():
    rows = [item(f"Line {n}", (str(n), None, None)) for n in range(20)]
    report = statements.build_report(rows, FY25, rank=lambda _, p: 100 + p)
    shown, note = statements.select(report.lines, accounts=None, detailed=False, key_limit=3)
    assert len(shown) == statements.FALLBACK_LINES
    assert "Showing 15 key lines of 20" in note
    assert statements.select([], accounts=["x"], detailed=False, key_limit=3) == ([], None)


def test_full_items_use_the_quarterly_prior_column():
    row = FnlttSinglAcntAllResponseListItem.model_validate(
        {
            "sj_div": "is",
            "account_id": "ifrs-full_Revenue",
            "account_nm": " Revenue ",
            "thstrm_amount": "10",
            "frmtrm_q_amount": "7",
            "frmtrm_amount": "99",
        }
    )
    reduced = statements.full_item(row)
    assert (reduced.statement, reduced.account, reduced.amounts[1]) == ("IS", "Revenue", "7")


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


@pytest.mark.anyio
async def test_gather_reraises_the_first_expected_error():
    async def ok():
        return 1

    async def broken():
        message = "upstream down"
        raise UpstreamError(message)

    assert await gather([ok, ok]) == [1, 1]
    with pytest.raises(UpstreamError, match="upstream down"):
        await gather([ok, broken])


def test_multi_company_rows_are_attributed_by_corp_code_or_stock_code():
    by_stock = {"000660": "00164779"}
    tagged = FnlttMultiAcntResponseListItem.model_validate(
        {"corp_code": "00126380", "stock_code": "005930"}
    )
    untagged = FnlttMultiAcntResponseListItem.model_validate({"stock_code": "000660"})
    unknown = FnlttMultiAcntResponseListItem.model_validate({"stock_code": "999999"})
    assert [_owner(row, by_stock) for row in (tagged, untagged, unknown)] == [
        "00126380",
        "00164779",
        None,
    ]


def test_holdings_without_a_total_line():
    holding = EquityInvestment(name="A", book_value=5, opening_book_value=4)
    periods, rows, investments, note = holdings_table(
        Holdings(H126, [holding], None, []), detailed=True, fye_month=12
    )
    assert [p.label for p in periods] == ["H1 2026", "FY2025"]
    assert [row.values for row in rows] == [[5, 4]]
    assert investments == [holding]
    assert note is None


def test_table_notes_and_sources():
    assert fallback_note([], FY25) is None
    assert (
        fallback_note([H126, FY25], FY25) == "OpenDART has no data for H1 2026 yet; showing FY2025."
    )
    numbers = ["20260310002820", "20260310002820 ", "bad", "20260814003699"]
    assert [s.filing_number for s in sources(numbers, None)] == ["20260310002820", "20260814003699"]

    class Resolved:
        candidates = ()

    assert "the requested period" in no_data(Resolved(), "things")


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
    result = PreliminaryResult(earnings=earnings, source=SourceFiling.of("20261008800004"))
    table = preliminary_table(result, fye_month=12, accounts=None)
    assert table.rows == []
    assert table.derived == {}
    assert table.basis == "separate"
    assert len(table.notes) == 1


# Balance-sheet lines as filed (ID, name) in Samsung's 2026 half-year report and in peers'
# (SK hynix, LG Energy Solution, Kakao), in upstream order; two are minor lines.
BALANCE = (
    ("ifrs-full_Assets", "Total assets"),
    ("ifrs-full_DeferredTaxAssets", "Deferred income tax assets"),
    ("ifrs-full_IntangibleAssetsOtherThanGoodwill", "Intangible assets"),
    (
        "ifrs-full_InvestmentsInSubsidiariesJointVenturesAndAssociates",
        "Investments in subsidiaries",
    ),
    (
        "ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets",
        "Property, plant and equipment",
    ),
    ("ifrs-full_RightofuseAssets", "Right-of-use assets"),
    ("dart_CapitalSurplus", "Capital surplus"),
    ("dart_CurrentLoansReceived", "Current loans received"),
    ("ifrs-full_AccrualsClassifiedAsCurrent", "Accrued expenses"),
    ("ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "Current borrowings"),
    ("ifrs-full_CurrentLeaseLiabilities", "Current lease liabilities"),
    ("ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers", "Trade payables"),
    ("ifrs-full_LongtermBorrowings", "Non-current portion of non-current borrowings"),
    ("ifrs-full_NoncurrentLeaseLiabilities", "Non-current lease liabilities"),
)


def test_concise_balance_sheets_show_operating_assets_and_all_debt():
    spec = statement_views.SPECS["balance"]
    items = [
        statements.Item("BS", name, account_id, "-", ("1", "1", None), (None, None), "x", "KRW")
        for account_id, name in BALANCE
    ]
    report = statements.build_report(items, H126, rank=spec.rank)
    shown, note = statements.select(
        report.lines, accounts=None, detailed=False, key_limit=spec.key_limit
    )
    assert [line.account for line in shown] == [
        "Total assets",
        "Property, plant and equipment",
        "Right-of-use assets",
        "Intangible assets",
        "Investments in subsidiaries",
        "Trade payables",
        "Current loans received",
        "Current borrowings",
        "Current lease liabilities",
        "Non-current portion of non-current borrowings",
        "Non-current lease liabilities",
        "Capital surplus",
    ]
    assert note is not None
    assert note.startswith("Showing 12 key lines of 14")
