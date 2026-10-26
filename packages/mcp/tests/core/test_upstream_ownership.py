"""Ownership and capital data access bound to the gateway: requests, records, and lifetimes."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from opendart_analysis.capital import period_share_counts
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.ownership import HoldingQuery
from opendart_analysis.reports import ReportQuery
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.upstream_ownership import (
    capital_changes_fetch,
    control_changes_fetch,
    insider_holdings_fetch,
    largest_holders_fetch,
    major_holdings_fetch,
    minority_holders_fetch,
    private_proceeds_fetch,
    public_proceeds_fetch,
    share_counts_fetch,
    treasury_stock_fetch,
)

FY2025 = PeriodRef(2025, "FY")
SHARES = {
    "rcept_no": "20260310002820",
    "se": "보통주",
    "istc_totqy": "100",
    "tesstk_co": "7",
    "distb_stock_co": "93",
    "stlm_dt": "2025-12-31",
}
REPORTS = [
    (largest_holders_fetch, "/hyslrSttus.json", "nm"),
    (control_changes_fetch, "/hyslrChgSttus.json", "mxmm_shrholdr_nm"),
    (minority_holders_fetch, "/mrhlSttus.json", "shrholdr_co"),
    (share_counts_fetch, "/stockTotqySttus.json", "se"),
    (treasury_stock_fetch, "/tesstkAcqsDspsSttus.json", "acqs_mth1"),
    (capital_changes_fetch, "/irdsSttus.json", "isu_dcrs_stle"),
    (public_proceeds_fetch, "/pssrpCptalUseDtls.json", "se_nm"),
    (private_proceeds_fetch, "/prvsrpCptalUseDtls.json", "se_nm"),
]


@pytest.fixture
def gateway(sdk):
    return Gateway(sdk, cache=TTLCache(max_weight=1000), concurrency=4, retry_delay=0)


@pytest.mark.anyio
@pytest.mark.parametrize(("factory", "path", "field"), REPORTS)
async def test_periodic_tables_are_read_with_the_period_arguments(
    gateway, upstream, factory, path, field
):
    upstream.records(path, {"rcept_no": "20260310002820", field: "value"})
    fetch = factory(lambda: gateway)
    rows = await fetch(ReportQuery("00126380", 2025, "11011"), volatility="low")
    assert rows is not None
    assert getattr(rows[0], field) == "value"
    query = upstream.params(path)[0]
    assert (query["corp_code"], query["bsns_year"], query["reprt_code"]) == (
        "00126380",
        "2025",
        "11011",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(("factory", "path", "field"), REPORTS[:2])
async def test_no_data_is_none(gateway, upstream, factory, path, field):
    del field
    upstream.route(path, upstream.status("013"))
    fetch = factory(lambda: gateway)
    assert await fetch(ReportQuery("00126380", 2024, "11011"), volatility="low") is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("factory", "path"),
    [(major_holdings_fetch, "/majorstock.json"), (insider_holdings_fetch, "/elestock.json")],
)
async def test_holding_reports_are_read_by_company(gateway, upstream, factory, path):
    upstream.records(path, {"rcept_no": "20261016000505", "repror": "삼성물산"})
    rows = await factory(lambda: gateway)(HoldingQuery("00126380"), volatility="medium")
    assert rows is not None
    assert rows[0].repror == "삼성물산"
    assert upstream.params(path)[0]["corp_code"] == "00126380"


@pytest.mark.anyio
async def test_a_missing_gateway_fails_only_when_called():
    def require_gateway():
        raise LookupError

    fetch = share_counts_fetch(require_gateway)
    with pytest.raises(LookupError):
        await fetch(ReportQuery("00126380", 2025, "11011"), volatility="low")


@pytest.mark.anyio
@pytest.mark.parametrize(("ref", "calls"), [(FY2025, 1), (PeriodRef(2026, "Q3"), 2)])
async def test_unsettled_share_counts_are_fetched_again_sooner(sdk, upstream, ref, calls):
    clock = [0.0]
    cache = TTLCache(max_weight=1000, clock=lambda: clock[0])
    gateway = Gateway(sdk, cache=cache, concurrency=4, retry_delay=0)
    company = SimpleNamespace(corp_code="00126380", fye_month=12)
    upstream.records("/stockTotqySttus.json", SHARES)
    fetch = share_counts_fetch(lambda: gateway)
    for _ in range(2):
        counts = await period_share_counts(
            company, ref, fetch_share_counts=fetch, today=date(2026, 10, 22)
        )
        assert counts is not None
        assert counts.outstanding == 93
        clock[0] += 16 * 60  # past the filing-list lifetime, well within a day
    assert upstream.count("/stockTotqySttus.json") == calls
