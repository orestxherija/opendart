"""The periodic-report extracts adapter: gateway arguments, cache lifetimes, provenance, and
errors are those of the server before the logic moved to ``opendart_analysis.extracts``."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.domain.periods import PeriodRef, PeriodicTitle
from opendart_analysis.errors import MissingDataError
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.errors import (
    API_KEY_MISSING,
    ConfigurationError,
    InvalidArgumentError,
    UpstreamError,
)
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.ttl import DAY, FILINGS
from opendart_mcp.models.common import CompanyRef, SourceFiling
from opendart_mcp.services.companies import Company
from opendart_mcp.services.extracts import fetch_records, fetch_response, gather_all, sources
from opendart_mcp.services.periods import PeriodicReport, periodic_ttl
from opendart_mcp.services.sdk_binding import sdk_method
from tests.support.events import filing, profile

COMPANY = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=12, profile=None)
TODAY = dt.date(2026, 10, 22)
TITLE = "Annual Report (2026.03)"


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
    state = SimpleNamespace(require_gateway=lambda: gateway, today=lambda: TODAY)
    assert await fetch_response(state, "alot_matter", company=COMPANY, ref=ref) is response
    assert await fetch_records(state, "alot_matter", company=COMPANY, ref=ref) == response.list
    expected = (
        periodic_ttl(state, COMPANY, ref),
        sdk_method(sdk, "alot_matter"),
        {
            "corporation_code": "00126380",
            "fiscal_year": str(ref.fiscal_year),
            "report_period": ref.report_code,
        },
    )
    assert expected[0] == ttl
    assert gateway.calls == [expected, expected]


@pytest.mark.anyio
async def test_the_request_reaches_opendart_unchanged(sdk, upstream):
    gateway = Gateway(sdk, cache=TTLCache(max_weight=1000), concurrency=4, retry_delay=0)
    state = SimpleNamespace(require_gateway=lambda: gateway, today=lambda: TODAY)
    upstream.route("/alotMatter.json", upstream.status("013"))
    ref = PeriodRef(2026, "H1")
    assert await fetch_records(state, "alot_matter", company=COMPANY, ref=ref) is None
    assert upstream.params("/alotMatter.json") == [
        {"corp_code": "00126380", "bsns_year": "2026", "reprt_code": "11012"}
    ]


@pytest.mark.anyio
async def test_a_keyless_server_reports_the_missing_key():
    def require_gateway():
        raise ConfigurationError(API_KEY_MISSING)

    state = SimpleNamespace(require_gateway=require_gateway, today=lambda: TODAY)
    with pytest.raises(ConfigurationError) as raised:
        await fetch_records(state, "alot_matter", company=COMPANY, ref=PeriodRef(2025, "FY"))
    assert str(raised.value) == API_KEY_MISSING


def test_provenance_becomes_source_filings_titled_by_the_report():
    ref = PeriodRef(2026, "FY", end_date=dt.date(2026, 3, 31))
    parsed = PeriodicTitle("annual", 2026, 3, None)
    report = PeriodicReport(ref, parsed, "20260625000111", TITLE, dt.date(2026, 6, 25))
    numbers = [" 20260625000111", None, "bad", "20260701000222", "20260625000111"]
    assert sources(numbers, report) == [
        SourceFiling.of("20260625000111", TITLE),
        SourceFiling.of("20260701000222"),
    ]


@pytest.mark.anyio
async def test_gathered_failures_stay_server_errors_with_their_messages():
    async def answer(value):
        return value

    async def fail(error):
        raise error

    assert await gather_all([answer(1), answer(2)]) == [1, 2]
    upstream_error = UpstreamError("OpenDART is unavailable.")
    with pytest.raises(UpstreamError) as raised:
        await gather_all([answer(1), fail(upstream_error)])
    assert raised.value is upstream_error
    with pytest.raises(InvalidArgumentError, match=r"^No data\.$") as translated:
        await gather_all([fail(MissingDataError("No data.")), answer(2)])
    assert isinstance(translated.value.__cause__, MissingDataError)


@pytest.mark.anyio
@pytest.mark.parametrize(("ref", "calls"), [(PeriodRef(2026, "H1"), 1), (PeriodRef(2026, "Q3"), 2)])
async def test_unsettled_periods_are_fetched_again_sooner(sdk, upstream, ref, calls):
    clock = [0.0]
    cache = TTLCache(max_weight=1000, clock=lambda: clock[0])
    gateway = Gateway(sdk, cache=cache, concurrency=4, retry_delay=0)
    state = SimpleNamespace(require_gateway=lambda: gateway, today=lambda: TODAY)
    upstream.records("/alotMatter.json", {"rcept_no": "20260814000123", "se": "x", "thstrm": "1"})
    for _ in range(2):
        assert await fetch_records(state, "alot_matter", company=COMPANY, ref=ref)
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
