"""Choosing the latest periodic report and the periods to probe."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.reports import PeriodUnavailableError
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.errors import API_KEY_MISSING, ConfigurationError, InvalidArgumentError
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.ttl import DAY, FILINGS
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.periods import latest_periodic_report, periodic_ttl, resolve_period

COMPANY = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=12, profile=None)


def filing(number, title):
    return {"rcept_no": number, "report_nm": title, "rcept_dt": number[:8], "corp_code": "00126380"}


@pytest.fixture
def state(sdk):
    gateway = Gateway(sdk, cache=TTLCache(max_weight=1000), concurrency=4, retry_delay=0)
    return SimpleNamespace(require_gateway=lambda: gateway, today=lambda: dt.date(2026, 10, 22))


@pytest.mark.anyio
async def test_an_amended_older_report_does_not_become_latest(state, upstream):
    upstream.records(
        "/list.json",
        filing("20260915000111", "[Revision of statements]Annual Report (2025.12)"),
        filing("20260814001234", "Semi-Annual Report (2026.06)"),
        filing("20260515000456", "Quarterly Report (2026.03)"),
    )
    report = await latest_periodic_report(state, COMPANY)
    assert report is not None
    assert (report.ref.period, report.ref.fiscal_year) == ("H1", 2026)


@pytest.mark.anyio
async def test_the_latest_filing_of_one_period_is_its_final_version(state, upstream):
    upstream.records(
        "/list.json",
        filing("20260916000222", "[Revision of statements]Annual Report (2025.12)"),
        filing("20260310000789", "Annual Report (2025.12)"),
    )
    report = await latest_periodic_report(state, COMPANY, "FY")
    assert report is not None
    assert report.filing_number == "20260916000222"


@pytest.mark.anyio
async def test_periods_after_the_latest_report_are_not_probed(state, upstream):
    upstream.records("/list.json", filing("20260814001234", "Semi-Annual Report (2026.06)"))
    resolved = await resolve_period(state, COMPANY, period="latest", fiscal_year=None)
    labels = [ref.label for ref in resolved.candidates]
    assert labels[0] == "H1 2026"
    assert "Q3 2026" not in labels
    assert labels[1:3] == ["Q1 2026", "FY2025"]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ((2026, "H1"), "day"),
        ((2026, "Q1"), "day"),
        ((2025, "FY"), "day"),
        ((2026, "Q3"), "short"),
    ],
)
def test_recent_periods_are_cached_briefly(state, label, expected):
    ref = PeriodRef(*label)
    assert periodic_ttl(state, COMPANY, ref) == (FILINGS if expected == "short" else DAY)


MARCH = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=3, profile=None)


@pytest.mark.anyio
async def test_both_labels_of_an_old_non_december_report_are_probed_first(state, upstream):
    # A late filer's newest report predates every deadline-based candidate.
    upstream.records("/list.json", filing("20260213000111", "Quarterly Report (2025.12)"))
    resolved = await resolve_period(state, MARCH, period="latest", fiscal_year=None)
    assert [ref.label for ref in resolved.candidates] == ["Q3 2026", "Q3 2025"]
    assert {ref.end_date for ref in resolved.candidates} == {dt.date(2025, 12, 31)}


def test_a_start_year_label_is_cached_by_its_period_end(state):
    june = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=6, profile=None)
    # Q1 of the year ending June 2027 ended 2026-09-30 and is due 2026-11-14.
    start_label = PeriodRef(2026, "Q1", end_date=dt.date(2026, 9, 30))
    assert periodic_ttl(state, june, start_label) == FILINGS
    assert periodic_ttl(state, june, PeriodRef(2026, "Q1")) == DAY


@pytest.mark.anyio
async def test_a_title_that_does_not_fit_the_fiscal_year_is_ignored(state, upstream):
    # A December year end has no quarterly report ending in December.
    upstream.records("/list.json", filing("20260213000111", "Quarterly Report (2025.12)"))
    assert await latest_periodic_report(state, COMPANY) is None


@pytest.mark.anyio
async def test_the_filing_search_is_sent_and_cached_as_before(state, upstream):
    upstream.records("/list.json", filing("20260814001234", "Semi-Annual Report (2026.06)"))
    for _ in range(2):
        assert await latest_periodic_report(state, COMPANY) is not None
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
