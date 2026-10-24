"""Choosing the periods to probe, and the latest periodic report through the gateway binding."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.reports import PeriodUnavailableError, latest_periodic_report
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.errors import API_KEY_MISSING, ConfigurationError, InvalidArgumentError
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.upstream import filing_search
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.periods import resolve_period

COMPANY = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=12, profile=None)


def filing(number, title):
    return {"rcept_no": number, "report_nm": title, "rcept_dt": number[:8], "corp_code": "00126380"}


async def latest(state, period="latest"):
    """Find the latest periodic report as the profile service does, through the gateway."""
    search = filing_search(state.require_gateway)
    return await latest_periodic_report(COMPANY, period, search_filings=search, today=state.today())


@pytest.fixture
def state(sdk):
    gateway = Gateway(sdk, cache=TTLCache(max_weight=1000), concurrency=4, retry_delay=0)
    return SimpleNamespace(require_gateway=lambda: gateway, today=lambda: dt.date(2026, 10, 22))


@pytest.mark.anyio
async def test_periods_after_the_latest_report_are_not_probed(state, upstream):
    upstream.records("/list.json", filing("20260814001234", "Semi-Annual Report (2026.06)"))
    resolved = await resolve_period(state, COMPANY, period="latest", fiscal_year=None)
    labels = [ref.label for ref in resolved.candidates]
    assert labels[0] == "H1 2026"
    assert "Q3 2026" not in labels
    assert labels[1:3] == ["Q1 2026", "FY2025"]


MARCH = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=3, profile=None)


@pytest.mark.anyio
async def test_both_labels_of_an_old_non_december_report_are_probed_first(state, upstream):
    # A late filer's newest report predates every deadline-based candidate.
    upstream.records("/list.json", filing("20260213000111", "Quarterly Report (2025.12)"))
    resolved = await resolve_period(state, MARCH, period="latest", fiscal_year=None)
    assert [ref.label for ref in resolved.candidates] == ["Q3 2026", "Q3 2025"]
    assert {ref.end_date for ref in resolved.candidates} == {dt.date(2025, 12, 31)}


@pytest.mark.anyio
async def test_the_filing_search_is_sent_and_cached_as_before(state, upstream):
    upstream.records("/list.json", filing("20260814001234", "Semi-Annual Report (2026.06)"))
    for _ in range(2):
        assert await latest(state) is not None
    assert upstream.params("/list.json") == [
        {
            "corp_code": "00126380",
            "bgn_de": "20250719",
            "end_de": "20261022",
            "pblntf_ty": "A",
            "last_reprt_at": "Y",
            "page_count": "100",
        }
    ]


@pytest.mark.anyio
async def test_an_unavailable_period_keeps_its_message(state):
    with pytest.raises(InvalidArgumentError) as raised:
        await resolve_period(state, COMPANY, period="FY", fiscal_year=2030)
    assert str(raised.value) == (
        "No FY 2030 period is available: it has not ended yet or predates 2015, when OpenDART's periodic data begins."
    )
    assert isinstance(raised.value.__cause__, PeriodUnavailableError)


@pytest.fixture
def keyless():
    def require_gateway():
        raise ConfigurationError(API_KEY_MISSING)

    return SimpleNamespace(require_gateway=require_gateway, today=lambda: dt.date(2026, 10, 22))


@pytest.mark.anyio
async def test_a_keyless_server_needs_the_gateway_only_to_search(keyless):
    resolved = await resolve_period(keyless, COMPANY, period="FY", fiscal_year=2024)
    assert [ref.label for ref in resolved.candidates] == ["FY2024"]
    with pytest.raises(InvalidArgumentError, match="No FY 2030 period"):
        await resolve_period(keyless, COMPANY, period="FY", fiscal_year=2030)
    with pytest.raises(ConfigurationError, match="API key is not configured"):
        await resolve_period(keyless, COMPANY, period="latest", fiscal_year=None)
