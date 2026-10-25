"""Peer comparison on synthetic multi-company records with a fixed date."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.errors import NotConfiguredError
from opendart_analysis.financials import (
    IndicatorsUnavailableError,
    Peer,
    PeerIndicatorQuery,
    PeerQuery,
    PeerRequest,
    compare_peers,
)
from opendart_analysis.financials.indicators import peer_volatility
from opendart_analysis.reports import PeriodUnavailableError
from packages.analysis.tests.financials.records import (
    ANNUAL,
    TODAY,
    Indicator,
    Row,
    Source,
    T,
    by_category,
    by_period,
    won,
)

pytestmark = pytest.mark.anyio

SAMSUNG = Peer("00126380", stock_code="005930")
HYNIX = Peer("00164779", stock_code="000660")
NAVER = Peer("00266961", fye_month=9)


@dataclass(frozen=True)
class TaggedRow(Row):
    corp_code: str | None = None


def accounts(corp, *, scope="CFS", revenue=300, tagged=True):
    owner = {"corp_code": corp.corp_code} if tagged else {"stock_code": corp.stock_code}
    rows = [
        ("IS", "Revenue", revenue, 250),
        ("IS", "Operating income", 30, 20),
        ("BS", "Total liabilities", 100, 90),
        ("BS", "Total equity", 200, 180),
    ]
    return tuple(
        TaggedRow(
            statement,
            account,
            current_period_amount=won(current),
            prior_period_amount=won(prior),
            statement_scope=scope,
            filing_number=ANNUAL,
            **owner,
        )
        for statement, account, current, prior in rows
    )


def recorder():
    messages = []

    async def progress(message):
        messages.append(message)

    return messages, progress


async def test_the_period_with_data_for_the_most_companies_wins():
    fetch = Source(
        {
            # A row that names neither a requested company nor its stock code is dropped.
            (2025, "11011"): (*accounts(SAMSUNG), TaggedRow("IS", "Revenue", stock_code="999999")),
            (2024, "11011"): (*accounts(SAMSUNG), *accounts(HYNIX, tagged=False)),
        },
        by_period,
    )
    messages, progress = recorder()
    comparison = await compare_peers(
        [SAMSUNG, HYNIX],
        request=PeerRequest(),
        fetch_peer_accounts=fetch,
        today=TODAY,
        progress=progress,
    )
    assert fetch.calls == [
        (PeerQuery(("00126380", "00164779"), 2025, "11011"), "low"),
        (PeerQuery(("00126380", "00164779"), 2024, "11011"), "low"),
    ]
    assert messages == ["Fetching FY2025 for 2 companies", "Fetching FY2024 for 2 companies"]
    assert (comparison.ref.label, comparison.newest.label, comparison.coverage) == (
        "FY2024",
        "FY2025",
        2,
    )
    samsung, hynix = comparison.peers
    assert samsung.basis == "consolidated"
    assert samsung.accounts == {
        "revenue": 300 * T,
        "operating_income": 30 * T,
        "total_liabilities": 100 * T,
        "total_equity": 200 * T,
        "revenue_growth": 20.0,
        "operating_income_growth": 50.0,
        "operating_margin": 10.0,
        "debt_to_equity": 50.0,
    }
    assert hynix.filings == (ANNUAL,) * 4
    assert comparison.indicators == ()
    assert comparison.notes == ()


async def test_basis_choice_per_company():
    rows = (*accounts(SAMSUNG), *accounts(HYNIX, scope="OFS"))
    fetch = Source({(2025, "11011"): rows}, by_period)
    auto = await compare_peers(
        [SAMSUNG, HYNIX], request=PeerRequest(basis="auto"), fetch_peer_accounts=fetch, today=TODAY
    )
    assert [peer.basis for peer in auto.peers] == ["consolidated", "separate"]
    strict = await compare_peers(
        [SAMSUNG, HYNIX, NAVER], request=PeerRequest(), fetch_peer_accounts=fetch, today=TODAY
    )
    _, hynix, naver = strict.peers
    assert (hynix.accounts, hynix.filed) == (None, True)
    assert (naver.accounts, naver.filed, naver.filings) == (None, False, ())


async def test_ratios_probe_profitability_then_read_every_category():
    published = {
        (2025, "11011", "M210000"): (
            Indicator("M211200", "Net profit margin", "10.5"),
            Indicator("M211200", "Net profit margin", "#########", corporation_code="00164779"),
        ),
        (2025, "11011", "M220000"): (Indicator("M221100", "Debt ratio", "50"),),
    }
    fetch = Source(published, by_category)
    messages, progress = recorder()
    comparison = await compare_peers(
        [SAMSUNG, HYNIX],
        request=PeerRequest(metrics="ratios", period="FY", fiscal_year=2025),
        fetch_peer_indicators=fetch,
        today=TODAY,
        progress=progress,
    )
    assert fetch.calls[0] == (
        PeerIndicatorQuery(("00126380", "00164779"), 2025, "11011", "M210000"),
        "low",
    )
    assert [query.category for query, _ in fetch.calls] == [
        "M210000",
        "M210000",
        "M220000",
        "M230000",
        "M240000",
    ]
    assert messages == ["Fetching FY2025 for 2 companies", "Fetching FY2025 indicators"]
    samsung, hynix = comparison.peers
    assert samsung.indicators == {"M211200": 10.5, "M221100": 50.0}
    assert hynix.indicators == {"M211200": None}
    assert (samsung.accounts, comparison.coverage) == (None, 1)
    assert [value.code for value in comparison.indicators] == ["M211200", "M211200", "M221100"]


async def test_indicators_before_2022_leave_only_accounts():
    fetch = Source({(2021, "11011"): accounts(SAMSUNG)}, by_period)
    ratios = Source({}, by_category)
    comparison = await compare_peers(
        [SAMSUNG],
        request=PeerRequest(metrics="both", fiscal_year=2021),
        fetch_peer_accounts=fetch,
        fetch_peer_indicators=ratios,
        today=TODAY,
    )
    assert comparison.notes == (
        "OpenDART publishes indicators from fiscal 2022; only accounts are shown.",
    )
    assert ratios.calls == []
    with pytest.raises(IndicatorsUnavailableError) as raised:
        await compare_peers(
            [SAMSUNG],
            request=PeerRequest(metrics="ratios", fiscal_year=2021),
            fetch_peer_indicators=ratios,
            today=TODAY,
        )
    assert raised.value.fiscal_year == 2021


async def test_no_data_and_unavailable_periods():
    empty = Source({}, by_period)
    assert (
        await compare_peers(
            [SAMSUNG], request=PeerRequest(), fetch_peer_accounts=empty, today=TODAY
        )
        is None
    )
    assert len(empty.calls) == 3
    with pytest.raises(PeriodUnavailableError) as raised:
        await compare_peers(
            [SAMSUNG],
            request=PeerRequest(fiscal_year=2030),
            fetch_peer_accounts=empty,
            today=TODAY,
        )
    assert str(raised.value) == (
        "No FY 2030 period is available: it has not ended yet or predates 2015, when OpenDART's periodic data begins."
    )


async def test_requests_name_the_missing_data_access_and_bound_the_companies():
    with pytest.raises(NotConfiguredError) as raised:
        await compare_peers([SAMSUNG], request=PeerRequest(metrics="both"), today=TODAY)
    assert raised.value.dependency == "fetch_peer_accounts"
    with pytest.raises(ValueError, match="Between 1 and 100 companies"):
        await compare_peers([], request=PeerRequest(), today=TODAY)
    with pytest.raises(ValueError, match="got 101"):
        PeerQuery(tuple(str(n) for n in range(101)), 2025, "11011")


async def test_periods_inside_their_filing_window_are_volatile():
    fetch = Source({}, by_period)
    for fiscal_year, period in ((2025, "FY"), (2026, "Q3")):
        request = PeerRequest(period=period, fiscal_year=fiscal_year)
        await compare_peers(
            [NAVER, SAMSUNG], request=request, fetch_peer_accounts=fetch, today=TODAY
        )
    # Q3 2026 ends on September 30 and is due on November 14.
    assert [volatility for _, volatility in fetch.calls] == ["low", "high"]


def test_peer_volatility_follows_each_fiscal_year_end():
    # Without an end date, a September year end puts Q3 2026 at June 30, past its deadline.
    recent = PeriodRef(2026, "Q3")
    assert peer_volatility([NAVER], recent, today=TODAY) == "low"
    assert peer_volatility([NAVER, SAMSUNG], recent, today=TODAY) == "high"
    assert peer_volatility([], recent, today=TODAY) == "low"
