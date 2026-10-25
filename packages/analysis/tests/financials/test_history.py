"""Statement, indicator, and holdings workflows on synthetic records with a fixed date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.financials import (
    MAX_REPORTS,
    HistoryRequest,
    IndicatorQuery,
    IndicatorsUnavailableError,
    ReportQuery,
    StatementQuery,
    StatementRequest,
    financial_statement,
    indicator_history,
    latest_holdings,
    major_accounts,
)
from opendart_analysis.financials.indicators import key, label
from opendart_analysis.financials.investments import opening_period
from opendart_analysis.reports import ResolvedPeriod, resolve_period
from packages.analysis.tests.financials.records import (
    ANNUAL,
    HALF,
    OLD_HALF,
    TODAY,
    Company,
    Filing,
    Indicator,
    Row,
    Source,
    T,
    by_category,
    by_period,
    by_scope,
    search,
    won,
)

pytestmark = pytest.mark.anyio

SAMSUNG = Company("00126380")
H126 = PeriodRef(2026, "H1", end_date=date(2026, 6, 30))
H125 = PeriodRef(2025, "H1")
H124 = PeriodRef(2024, "H1")
FY25 = PeriodRef(2025, "FY")


def summary(statement, account, current, prior=None, cumulative=(None, None), **extra):
    return Row(
        statement,
        account,
        current_period_amount=won(current),
        prior_period_amount=won(prior),
        current_period_cumulative_amount=won(cumulative[0]),
        prior_period_cumulative_amount=won(cumulative[1]),
        **extra,
    )


# Half-year major accounts: income lines hold three months with the year to date alongside.
HALF_YEAR = (
    summary("IS", "Sales", 170, 75, (300, 150)),
    summary("IS", "Operating income", 90, 5, (145, 11)),
    summary("IS", "Profit", 72, 5, (118, 13)),
    summary("BS", "Current assets", 380, 250),
    summary("BS", "Total assets", 760, 570),
    summary("BS", "Current liabilities", 135, 100),
    summary("BS", "Total liabilities", 180, 125),
    summary("BS", "Total equity", 580, 445),
    summary("IS", "Sales", 1, statement_scope="OFS"),
)
# The prior half-year report as first filed; the newer report restated its revenue.
PRIOR_HALF = (summary("IS", "Sales", 76, 60, (150, 120), filing_number=OLD_HALF),)


def recorder():
    messages = []

    async def progress(message):
        messages.append(message)

    return messages, progress


async def test_latest_major_accounts_end_to_end():
    company = SAMSUNG
    resolved = await resolve_period(
        company,
        period="latest",
        fiscal_year=None,
        search_filings=search(Filing(HALF, "Semi-Annual Report (2026.06)")),
        today=TODAY,
    )
    fetch = Source({(2026, "11012"): HALF_YEAR, (2025, "11012"): PRIOR_HALF}, by_period)
    messages, progress = recorder()
    history = await major_accounts(
        company,
        resolved,
        request=HistoryRequest(years=2),
        fetch_major_accounts=fetch,
        today=TODAY,
        progress=progress,
    )
    assert history.ref == H126
    assert fetch.calls == [
        (ReportQuery("00126380", 2026, "11012"), "low"),
        (ReportQuery("00126380", 2025, "11012"), "low"),
    ]
    assert messages == ["Fetching H1 2026", "2/2 Fetching H1 2025"]
    report = history.report
    assert (report.basis, report.currency, report.filings) == (
        "consolidated",
        "KRW",
        (HALF, OLD_HALF),
    )
    revenue = next(line for line in report.lines if line.account == "Sales")
    assert revenue.rank == 0
    assert revenue.values == {H126: 170 * T, H125: 75 * T, H124: 60 * T}
    assert revenue.cumulative == {H126: 300 * T, H125: 150 * T, H124: 120 * T}
    assert [line.account for line in sorted(report.lines, key=lambda line: line.rank)][:3] == [
        "Sales",
        "Operating income",
        "Profit",
    ]
    # Growth and margins use year-to-date amounts, the balance sheet the period end.
    assert history.derived == {
        "revenue_growth": 100.0,
        "operating_income_growth": 1218.18,
        "net_income_growth": 807.69,
        "operating_margin": 48.33,
        "net_margin": 39.33,
        "debt_to_equity": 31.03,
        "current_ratio": 281.48,
    }
    assert history.notes == ()


def balance(account_id, account, current, prior=None, **extra):
    return Row(
        "BS",
        account,
        current_period_amount=won(current),
        prior_period_amount=won(prior),
        account_id=account_id,
        statement_scope=None,
        filing_number=ANNUAL,
        **extra,
    )


SEPARATE_BALANCE = (
    balance("ifrs-full_Inventories", "Inventories", 50, 40),
    balance("ifrs-full_Liabilities", "Total liabilities", 100, 90),
    balance("ifrs-full_Assets", "Total assets", 400, 380),
    balance("ifrs-full_Equity", "Total equity", 300, 290),
    balance("dart_Other", "Other", 1, 1),
)


async def test_auto_basis_falls_back_to_separate_and_chains_keep_it():
    resolved = await resolve_period(
        SAMSUNG, period="FY", fiscal_year=2025, search_filings=search(), today=TODAY
    )
    fetch = Source({(2025, "11011", "OFS"): SEPARATE_BALANCE}, by_scope)
    history = await financial_statement(
        SAMSUNG,
        resolved,
        request=StatementRequest("balance", years=2),
        fetch_full_statements=fetch,
        today=TODAY,
    )
    assert [(query.fiscal_year, query.scope) for query, _ in fetch.calls] == [
        (2025, "CFS"),
        (2025, "OFS"),
        (2022, "OFS"),
    ]
    assert fetch.calls[0] == (StatementQuery("00126380", 2025, "11011", "CFS"), "low")
    assert history.report.basis == "separate"
    ranked = sorted(history.report.lines, key=lambda line: line.rank)
    assert [line.account for line in ranked] == [
        "Total assets",
        "Inventories",
        "Total liabilities",
        "Total equity",
        "Other",
    ]
    # An annual report's third column is blank here, which leaves FY2023 missing.
    assert ranked[0].values == {
        FY25: 400 * T,
        PeriodRef(2024, "FY"): 380 * T,
        PeriodRef(2023, "FY"): None,
    }
    assert history.derived == {"debt_to_equity": 33.33}
    assert history.notes == ("No data for FY2022; earlier columns are missing.",)


async def test_income_falls_back_to_a_single_comprehensive_income_statement():
    resolved = ResolvedPeriod((FY25,), None, None)
    rows = (
        Row("CIS", "Revenue", "100", account_id="ifrs-full_Revenue", statement_scope=None),
        Row("BS", "Total assets", "9", account_id="ifrs-full_Assets", statement_scope=None),
    )
    fetch = Source({(2025, "11011", "CFS"): rows}, by_scope)
    history = await financial_statement(
        SAMSUNG,
        resolved,
        request=StatementRequest("income"),
        fetch_full_statements=fetch,
        today=TODAY,
    )
    assert [line.key for line in history.report.lines] == ["CIS:ifrs-full_Revenue"]
    assert history.report.basis == "consolidated"


async def test_no_data_on_the_requested_basis_is_none():
    resolved = ResolvedPeriod((FY25, PeriodRef(2024, "FY")), None, "chosen by deadlines")
    fetch = Source(
        {(2025, "11011"): (summary("IS", "Sales", 1, statement_scope="OFS"),)}, by_period
    )
    request = HistoryRequest(basis="consolidated")
    assert (
        await major_accounts(
            SAMSUNG, resolved, request=request, fetch_major_accounts=fetch, today=TODAY
        )
        is None
    )
    assert len(fetch.calls) == 2


async def test_a_fallback_period_is_noted():
    resolved = ResolvedPeriod((PeriodRef(2026, "Q3"), H126), None, "chosen by deadlines")
    fetch = Source({(2026, "11012"): HALF_YEAR}, by_period)
    history = await major_accounts(
        SAMSUNG, resolved, request=HistoryRequest(), fetch_major_accounts=fetch, today=TODAY
    )
    assert history.notes == (
        "chosen by deadlines",
        "OpenDART has no data for Q3 2026 yet; showing H1 2026.",
    )
    # Q3 2026 is still inside its filing window on the fixed date.
    assert [volatility for _, volatility in fetch.calls] == ["high", "low"]


@pytest.mark.parametrize("years", [0, MAX_REPORTS + 1])
def test_requests_bound_the_reports_chained(years):
    with pytest.raises(ValueError, match="years must be between 1 and 10"):
        HistoryRequest(years=years)
    with pytest.raises(ValueError, match="years must be between 1 and 10"):
        StatementRequest("income", years=years)


async def test_indicator_history_ranks_key_indicators_and_keeps_overflow_missing():
    resolved = ResolvedPeriod((FY25,), None, None)
    published = (
        Indicator("M219999", "Some ratio", "#########"),
        Indicator("M211200", "Net profit margin", "10.5"),
        Indicator(None, "No code", "1"),
    )
    fetch = Source({(2025, "11011", "M210000"): published}, by_category)
    history = await indicator_history(
        SAMSUNG, resolved, years=1, fetch_indicators=fetch, today=TODAY
    )
    assert [query.category for query, _ in fetch.calls] == [
        "M210000",
        "M220000",
        "M230000",
        "M240000",
    ]
    assert fetch.calls[0] == (IndicatorQuery("00126380", 2025, "11011", "M210000"), "low")
    lines = sorted(history.report.lines, key=lambda line: line.rank)
    assert [(line.account, line.kind, line.values) for line in lines] == [
        ("Net margin", "percent", {FY25: 10.5}),
        ("Some ratio", "percent", {FY25: None}),
    ]
    assert history.report.basis is None
    assert history.derived == {}


async def test_indicators_predate_fiscal_2022():
    resolved = ResolvedPeriod((PeriodRef(2021, "FY"),), None, None)
    fetch = Source({}, by_category)
    with pytest.raises(IndicatorsUnavailableError) as raised:
        await indicator_history(SAMSUNG, resolved, years=1, fetch_indicators=fetch, today=TODAY)
    assert (raised.value.fiscal_year, raised.value.first_indicator_year) == (2021, 2022)
    assert (
        str(raised.value)
        == "OpenDART publishes financial indicators from fiscal 2022, so fiscal 2021 has none."
    )
    assert fetch.calls == []
    empty = ResolvedPeriod((PeriodRef(2023, "FY"),), None, None)
    assert (
        await indicator_history(SAMSUNG, empty, years=1, fetch_indicators=fetch, today=TODAY)
        is None
    )


@dataclass(frozen=True)
class Investee:
    inv_prm: str | None
    trmend_blce_acntbk_amount: str | None
    invstmnt_purps: str | None = None
    frst_acqs_de: str | None = None
    bsis_blce_acntbk_amount: str | None = None
    incrs_dcrs_acqs_dsps_amount: str | None = None
    incrs_dcrs_evl_lstmn: str | None = None
    trmend_blce_qy: str | None = None
    trmend_blce_qota_rt: str | None = None
    recent_bsns_year_fnnr_sttus_tot_assets: str | None = None
    recent_bsns_year_fnnr_sttus_thstrm_ntpf: str | None = None
    filing_number: str | None = HALF


async def test_holdings_come_from_the_newest_period_with_a_table():
    resolved = ResolvedPeriod((PeriodRef(2026, "Q3"), H126), None, None)
    rows = (
        Investee("A Corp", "5,000", "경영참여", "2019.03.04", "4,000", trmend_blce_qota_rt="12.5"),
        Investee("B Corp", "9,000", "단순 투자", trmend_blce_qy="1,200"),
        Investee("Other Co", "300", "Strategic"),
        Investee("소계", "14,300"),
        Investee("합계", "14,300"),
    )
    fetch = Source({(2026, "11012"): rows}, by_period)
    messages, progress = recorder()
    holdings = await latest_holdings(
        SAMSUNG, resolved, fetch_investments=fetch, today=TODAY, progress=progress
    )
    assert messages == ["Fetching Q3 2026", "Fetching H1 2026"]
    assert holdings.ref == H126
    assert [(h.name, h.book_value, h.purpose) for h in holdings.investments] == [
        ("B Corp", 9000, "simple investment"),
        ("A Corp", 5000, "management participation"),
        ("Other Co", 300, "Strategic"),
    ]
    first = holdings.investments[1]
    assert (first.first_acquired, first.opening_book_value, first.ownership_pct) == (
        date(2019, 3, 4),
        4000,
        12.5,
    )
    assert holdings.investments[0].shares == 1200
    assert (holdings.total.name, holdings.total.book_value) == ("합계", 14300)
    assert holdings.filings == (HALF,)


async def test_equity_changes_rank_by_component_from_opening_to_closing_balance():
    retained = "자본 [구성요소]|이익잉여금 [구성요소]"

    def change(account_id, account, amount, detail=retained):
        return Row(
            "SCE",
            account,
            amount,
            account_id=account_id,
            account_detail=detail,
            statement_scope=None,
        )

    rows = (
        change("ifrs-full_Equity", "Equity at end", "110"),
        change("ifrs-full_ProfitLoss", "Profit", "10"),
        change("dart_EquityAtBeginningOfPeriod", "Equity at beginning", "100"),
        change("dart_EquityAtBeginningOfPeriod", "Equity at beginning", "500", "자본 [구성요소]"),
    )
    fetch = Source({(2025, "11011", "CFS"): rows}, by_scope)
    history = await financial_statement(
        SAMSUNG,
        ResolvedPeriod((FY25,), None, None),
        request=StatementRequest("equity_changes"),
        fetch_full_statements=fetch,
        today=TODAY,
    )
    ranked = sorted(history.report.lines, key=lambda line: line.rank)
    assert [(line.account, line.key) for line in ranked] == [
        ("Equity at beginning", "SCE:dart_EquityAtBeginningOfPeriod:Total"),
        (
            "Equity at beginning (Retained earnings)",
            "SCE:dart_EquityAtBeginningOfPeriod:Retained earnings",
        ),
        ("Profit (Retained earnings)", "SCE:ifrs-full_ProfitLoss:Retained earnings"),
        ("Equity at end (Retained earnings)", "SCE:ifrs-full_Equity:Retained earnings"),
    ]
    assert history.derived == {}


def test_opening_balances_refer_to_the_prior_fiscal_year_end():
    assert opening_period(FY25) == PeriodRef(2024, "FY")
    assert opening_period(H126) == PeriodRef(2025, "FY")
    assert opening_period(H126).end_date == date(2025, 12, 31)


def test_indicators_have_stable_keys_and_clear_labels():
    assert (key("M211200"), label("M211200", "Net profit margin")) == ("net_margin", "Net margin")
    assert (key("M999999"), label("M999999", "As published")) == ("m999999", "As published")
