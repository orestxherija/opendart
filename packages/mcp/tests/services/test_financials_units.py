"""Unit tests for the get_financials and compare_companies adapters, without the MCP protocol.

The calculations they build on are tested in ``packages/analysis/tests/financials``; the tests
here cover the presentation policy and that SDK records work as analysis records at runtime.
"""

from __future__ import annotations

from datetime import date

import pytest

from opendart.models.financial_statements import (
    FnlttMultiAcntResponseListItem,
    FnlttSinglAcntAllResponseListItem,
)
from opendart_analysis.documents.preliminary import PreliminaryEarnings, PreliminaryPeriod
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.financials import Holding, Holdings, PeerValues
from opendart_analysis.financials.peers import owner
from opendart_analysis.financials.specs import STATEMENTS
from opendart_analysis.financials.statements import Item, build_report, full_item
from opendart_mcp.core.errors import UpstreamError
from opendart_mcp.models.common import CompanyRef, SourceFiling
from opendart_mcp.models.financials import EquityInvestment
from opendart_mcp.models.preliminary import PreliminaryResult
from opendart_mcp.services import peer_table, statements
from opendart_mcp.services.companies import Company
from opendart_mcp.services.compare import CompareRequest
from opendart_mcp.services.fanout import gather
from opendart_mcp.services.investments import holdings_table
from opendart_mcp.services.preliminary_table import preliminary_table
from opendart_mcp.services.tables import no_data, sources

FY25 = PeriodRef(2025, "FY", end_date=date(2025, 12, 31))
H126 = PeriodRef(2026, "H1", end_date=date(2026, 6, 30))


def test_columns_fill_end_dates_from_the_fiscal_year_end():
    assert statements.column(PeriodRef(2025, "Q3"), fye_month=12).end_date == date(2025, 9, 30)
    assert statements.column(H126, fye_month=12).label == "H1 2026"


def item(account, amounts, *, statement="IS", account_id=None, cumulative=(None, None)):
    return Item(statement, account, account_id, None, amounts, cumulative, "20260310002820", "KRW")


def test_concise_selection_falls_back_when_few_key_lines():
    rows = [item(f"Line {n}", (str(n), None, None)) for n in range(20)]
    report = build_report(rows, FY25, rank=lambda _, p: 100 + p)
    shown, note = statements.select(report.lines, accounts=None, detailed=False, key_limit=3)
    assert len(shown) == statements.FALLBACK_LINES
    assert "Showing 15 key lines of 20" in note
    assert statements.select([], accounts=["x"], detailed=False, key_limit=3) == ([], None)
    _, missing = statements.select(report.lines, accounts=["zzz"], detailed=False, key_limit=3)
    assert missing.startswith("No line matches accounts=['zzz']; lines include Line 0, Line 1")


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
    # SDK records satisfy the analysis record Protocols at runtime, as pyrefly proves statically.
    reduced = full_item(row)
    assert (reduced.statement, reduced.account, reduced.amounts[1]) == ("IS", "Revenue", "7")


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
    assert [owner(row, by_stock) for row in (tagged, untagged, unknown)] == [
        "00126380",
        "00164779",
        None,
    ]


def holding(name, book_value, opening_book_value):
    return Holding(
        name, None, None, None, book_value, date(2020, 1, 2), opening_book_value, *[1] * 4
    )


def test_holdings_without_a_total_line():
    stake = holding("A", 5, 4)
    periods, rows, investments, note = holdings_table(
        Holdings(H126, (stake,), None, ()), detailed=True, fye_month=12
    )
    assert [p.label for p in periods] == ["H1 2026", "FY2025"]
    assert [row.values for row in rows] == [[5, 4]]
    assert investments == [
        EquityInvestment(
            name="A",
            book_value=5,
            first_acquired=date(2020, 1, 2),
            opening_book_value=4,
            acquired_or_disposed=1,
            valuation_change=1,
            investee_total_assets=1,
            investee_net_income=1,
        )
    ]
    assert note is None


def test_concise_holdings_keep_the_largest_and_drop_detail_fields():
    stakes = tuple(holding(f"H{n}", 100 - n, None) for n in range(25))
    _, rows, investments, note = holdings_table(
        Holdings(FY25, stakes, holding("Total", 999, 900), ()), detailed=False, fye_month=12
    )
    assert len(investments) == 20
    assert rows[-1].account == "Total (all investments)"
    assert investments[0] == EquityInvestment(name="H0", book_value=100)
    assert note.startswith("Showing the 20 largest of 25 holdings by book value")


def test_table_sources_and_empty_notes():
    numbers = ["20260310002820", "20260310002820 ", "bad", "20260814003699"]
    assert [s.filing_number for s in sources(numbers, None)] == ["20260310002820", "20260814003699"]

    class Resolved:
        candidates = ()

    assert "the requested period" in no_data(Resolved(), "things")


def test_preliminary_tables_without_rows_keep_their_notes():
    earnings = PreliminaryEarnings(
        filing_number="1",
        basis="separate",
        periods=[PreliminaryPeriod(key="current_quarter", label_ko="x", end="2026-03-31")],
        rows=[],
        is_amendment=False,
    )
    result = PreliminaryResult(earnings=earnings, source=SourceFiling.of("20261008800004"))
    table = preliminary_table(result, fye_month=12, accounts=None)
    assert [p.label for p in table.periods] == ["Q1 2026", "Q4 2025", "Q1 2025"]
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
    spec = STATEMENTS["balance"]
    items = [
        Item("BS", name, account_id, "-", ("1", "1", None), (None, None), "x", "KRW")
        for account_id, name in BALANCE
    ]
    report = build_report(items, H126, rank=spec.rank)
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


def test_peer_rows_explain_why_a_company_is_missing():
    company = Company(
        ref=CompanyRef(name="Example", corp_code="00000001"), fye_month=12, profile=None
    )
    request = CompareRequest()
    unfiled = PeerValues("00000001", None, None, filed=False)
    other_basis = PeerValues("00000001", None, None, filed=True)
    assert (
        peer_table.row(company, unfiled, ref=FY25, columns=[], request=request)
        == "No FY2025 data in OpenDART (not filed yet, or not covered)."
    )
    assert (
        peer_table.row(company, other_basis, ref=FY25, columns=[], request=request)
        == 'No consolidated statements for FY2025; pass basis="auto".'
    )
