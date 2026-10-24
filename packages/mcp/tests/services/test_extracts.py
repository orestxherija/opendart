"""Periodic-report extracts: the fiscal-year labels a filed report is probed under, and how
long answers are cached."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.domain.periods import PeriodRef, PeriodicTitle
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.extracts import checked, fetch_records, probe_attempts
from opendart_mcp.services.periods import PROBE_ATTEMPTS, PeriodicReport, ResolvedPeriod
from tests.support.events import filing, profile

COMPANY = Company(ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=12, profile=None)
MARCH_END = dt.date(2026, 3, 31)
TITLE = "Annual Report (2026.03)"


def report(ref):
    parsed = PeriodicTitle("annual", 2026, 3, None)
    return PeriodicReport(ref, parsed, "20260625000111", TITLE, dt.date(2026, 6, 25))


def test_without_a_report_the_shared_probe_limit_applies():
    resolved = ResolvedPeriod((PeriodRef(2026, "H1"), PeriodRef(2026, "Q1")), None, "note")
    assert probe_attempts(resolved) == PROBE_ATTEMPTS
    assert checked(resolved) == "H1 2026, Q1 2026"


def test_a_december_report_is_read_under_its_one_label():
    ref = PeriodRef(2025, "FY", end_date=dt.date(2025, 12, 31))
    older = PeriodRef(2025, "Q3", end_date=dt.date(2025, 9, 30))
    assert probe_attempts(ResolvedPeriod((ref, older), report(ref), None)) == 1


def test_a_march_report_is_read_under_both_labels_of_its_period():
    ref = PeriodRef(2026, "FY", end_date=MARCH_END)
    start_label = PeriodRef(2025, "FY", end_date=MARCH_END)
    year_before = PeriodRef(2025, "FY", end_date=dt.date(2025, 3, 31))
    resolved = ResolvedPeriod((ref, start_label, year_before), report(ref), None)
    assert probe_attempts(resolved) == 2
    assert checked(resolved) == f'"{TITLE}"'


def test_a_report_without_an_end_date_is_read_once():
    ref = PeriodRef(2026, "FY")
    assert probe_attempts(ResolvedPeriod((ref, PeriodRef(2025, "FY")), report(ref), None)) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(("ref", "calls"), [(PeriodRef(2026, "H1"), 1), (PeriodRef(2026, "Q3"), 2)])
async def test_unsettled_periods_are_fetched_again_sooner(sdk, upstream, ref, calls):
    clock = [0.0]
    cache = TTLCache(max_weight=1000, clock=lambda: clock[0])
    gateway = Gateway(sdk, cache=cache, concurrency=4, retry_delay=0)
    state = SimpleNamespace(require_gateway=lambda: gateway, today=lambda: dt.date(2026, 10, 22))
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
