"""Periodic-report extracts through the gateway binding: the requests, cache lifetimes, and
configuration error that services get when they pass ``service_fetch`` to
``opendart_analysis.extracts``."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.extracts import fetch_records, fetch_response
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.errors import API_KEY_MISSING, ConfigurationError
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.sdk_binding import sdk_method
from opendart_mcp.core.ttl import DAY, FILINGS
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from scripts.testing.events import filing, profile

COMPANY = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=12, profile=None)
TODAY = dt.date(2026, 10, 22)
TITLE = "Annual Report (2026.03)"


def _call(ref: PeriodRef) -> dict[str, object]:
    """Name the dividend service for the company and a period, as services do."""
    return {"service": "alot_matter", "company": COMPANY, "ref": ref, "today": TODAY}


class _Gateway:
    """Records gateway calls and answers each with a fixed response."""

    def __init__(self, sdk: object, response: object) -> None:
        self.sdk = sdk
        self.response = response
        self.calls: list[tuple[float, object, dict[str, object]]] = []

    async def call(self, ttl: float, method: object, **kwargs: object) -> object:
        self.calls.append((ttl, method, kwargs))
        return self.response


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("ref", "ttl"), [(PeriodRef(2026, "Q3"), FILINGS), (PeriodRef(2024, "FY"), DAY)]
)
async def test_the_gateway_is_called_with_the_same_arguments_and_lifetime(sdk, ref, ttl):
    response = SimpleNamespace(list=[SimpleNamespace(rcept_no="20260814000123")])
    gateway = _Gateway(sdk, response)
    fetch = service_fetch(lambda: gateway)
    assert await fetch_response(**_call(ref), fetch_service=fetch) is response
    assert await fetch_records(**_call(ref), fetch_service=fetch) == response.list
    expected = (
        ttl,
        sdk_method(sdk, "alot_matter"),
        {
            "corporation_code": "00126380",
            "fiscal_year": str(ref.fiscal_year),
            "report_period": ref.report_code,
        },
    )
    assert gateway.calls == [expected, expected]


@pytest.mark.anyio
async def test_the_request_reaches_opendart_unchanged(sdk, upstream):
    gateway = Gateway(sdk, cache=TTLCache(max_weight=1000), concurrency=4, retry_delay=0)
    upstream.route("/alotMatter.json", upstream.status("013"))
    fetch = service_fetch(lambda: gateway)
    assert await fetch_records(**_call(PeriodRef(2026, "H1")), fetch_service=fetch) is None
    assert upstream.params("/alotMatter.json") == [
        {"corp_code": "00126380", "bsns_year": "2026", "reprt_code": "11012"}
    ]


@pytest.mark.anyio
async def test_a_keyless_server_reports_the_missing_key():
    def require_gateway():
        raise ConfigurationError(API_KEY_MISSING)

    fetch = service_fetch(require_gateway)
    with pytest.raises(ConfigurationError) as raised:
        await fetch_records(**_call(PeriodRef(2025, "FY")), fetch_service=fetch)
    assert str(raised.value) == API_KEY_MISSING


@pytest.mark.anyio
@pytest.mark.parametrize(("ref", "calls"), [(PeriodRef(2026, "H1"), 1), (PeriodRef(2026, "Q3"), 2)])
async def test_unsettled_periods_are_fetched_again_sooner(sdk, upstream, ref, calls):
    clock = [0.0]
    cache = TTLCache(max_weight=1000, clock=lambda: clock[0])
    gateway = Gateway(sdk, cache=cache, concurrency=4, retry_delay=0)
    upstream.records("/alotMatter.json", {"rcept_no": "20260814000123", "se": "x", "thstrm": "1"})
    fetch = service_fetch(lambda: gateway)
    for _ in range(2):
        assert await fetch_records(**_call(ref), fetch_service=fetch)
        clock[0] += 16 * 60
    assert upstream.count("/alotMatter.json") == calls


DIVIDEND = {
    "rcept_no": "20260625000111",
    "se": "Cash dividend per share (KRW)",
    "stock_knd": "보통주",
    "thstrm": "1,668",
    "frmtrm": "1,446",
    "lwfr": "1,444",
    "stlm_dt": "2026-03-31",
}


@pytest.mark.anyio
@pytest.mark.parametrize("label", ["2026", "2025"])
async def test_dividends_of_a_march_year_end_are_found_under_either_label(client, upstream, label):
    upstream.route("/company.json", upstream.ok(**{**profile(), "acc_mt": "03"}))
    upstream.records("/list.json", filing("20260625000111", TITLE))

    def by_label(request):
        found = request.url.params.get("bsns_year") == label
        return upstream.rows(DIVIDEND) if found else upstream.status("013")

    upstream.route("/alotMatter.json", by_label)
    result = await client.call_tool("get_dividends", {"company": "005930"}, raise_on_error=False)
    data = result.structured_content
    years = [query["bsns_year"] for query in upstream.params("/alotMatter.json")]
    assert years == (["2026"] if label == "2026" else ["2026", "2025"])
    assert data["fiscal_years"][0] == int(label)
    (row,) = data["rows"]
    assert row["values_by_year"][label] == 1668
