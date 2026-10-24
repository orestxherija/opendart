"""The calendar's shared bound on upstream calls in flight, across every company it reads."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import anyio.lowlevel
import pytest

from opendart_analysis.calendar import (
    MAX_CONCURRENCY,
    CalendarSubject,
    calendar_window,
    corporate_action_calendar,
    read_debt_maturities,
)
from opendart_analysis.catalog import EVENT_KINDS
from opendart_analysis.events import CALENDAR_KINDS, ReadPolicy
from opendart_analysis.upstream import CallLimit

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
WINDOW = calendar_window("90d", today=TODAY)
WATCHLIST = [CalendarSubject(f"00{index:06d}", f"Company {index}") for index in range(20)]
DATED = tuple(kind for kind in EVENT_KINDS if kind in CALENDAR_KINDS)
TITLES = (
    "Decision on Issuance of Convertible Bonds",
    "Decision on Merger",
    "Decision on Acquisition of Treasury Stock",
)


class Gauge:
    """Data access that records the most calls in flight at once, across every callable."""

    def __init__(self) -> None:
        self.now = 0
        self.peak = 0
        self.calls = 0

    async def _hold(self) -> None:
        self.now += 1
        self.calls += 1
        self.peak = max(self.peak, self.now)
        try:
            await anyio.lowlevel.checkpoint()
            await anyio.lowlevel.checkpoint()
        finally:
            self.now -= 1

    async def read_filing_page(self, query, /, *, volatility):
        assert volatility == "high"
        await self._hold()
        if query.group != "B":
            return None
        rows = [
            SimpleNamespace(filing_number=f"2026090{n}000123", report_title=title)
            for n, title in enumerate(TITLES, start=1)
        ]
        return SimpleNamespace(list=rows, total_count=len(rows), total_page=1)

    async def fetch_service(self, service, /, *, volatility, **params):
        del service, volatility, params
        await self._hold()

    async def search_filings(self, query, /, *, volatility):
        del query, volatility
        await self._hold()
        return [SimpleNamespace(filing_number="20260814001234", report_title="Semi-Annual Report")]


async def test_the_default_limit_bounds_every_company_together():
    gauge = Gauge()
    calendar = await corporate_action_calendar(
        WATCHLIST,
        window=WINDOW,
        fetch_service=gauge.fetch_service,
        read_filing_page=gauge.read_filing_page,
        today=TODAY,
    )
    assert len(calendar.companies) == 20
    assert gauge.calls > 20 * len(TITLES)  # Index pages and services of every company.
    assert gauge.peak == MAX_CONCURRENCY == 5


async def test_a_shared_limit_also_bounds_the_debt_reader():
    gauge = Gauge()
    limit = CallLimit(3)
    maturities = read_debt_maturities(
        search_filings=gauge.search_filings,
        fetch_service=gauge.fetch_service,
        today=TODAY,
        limit=limit,
    )
    calendar = await corporate_action_calendar(
        WATCHLIST,
        window=WINDOW,
        kinds=DATED,
        maturities=maturities,
        fetch_service=gauge.fetch_service,
        read_filing_page=gauge.read_filing_page,
        policy=ReadPolicy(concurrency=2),
        limit=limit,
        today=TODAY,
    )
    assert all(company.maturities is not None for company in calendar.companies)
    assert gauge.calls > 20 * len(DATED)
    assert gauge.peak == 3


async def test_an_int_limit_is_a_new_limit_per_calendar():
    gauge = Gauge()
    await corporate_action_calendar(
        WATCHLIST,
        window=WINDOW,
        kinds=DATED,
        fetch_service=gauge.fetch_service,
        read_filing_page=gauge.read_filing_page,
        limit=1,
        today=TODAY,
    )
    assert gauge.peak == 1


async def test_no_limit_leaves_the_bound_to_the_source():
    gauge = Gauge()
    await corporate_action_calendar(
        WATCHLIST,
        window=WINDOW,
        fetch_service=gauge.fetch_service,
        read_filing_page=gauge.read_filing_page,
        limit=None,
        today=TODAY,
    )
    assert gauge.peak > MAX_CONCURRENCY


async def test_a_limit_below_one_fails_before_any_call():
    gauge = Gauge()
    with pytest.raises(ValueError, match="at least 1"):
        await corporate_action_calendar(
            WATCHLIST,
            window=WINDOW,
            fetch_service=gauge.fetch_service,
            read_filing_page=gauge.read_filing_page,
            limit=0,
            today=TODAY,
        )
    assert gauge.calls == 0


async def test_bounding_a_bound_callable_again_returns_it_unchanged():
    gauge = Gauge()
    limit = CallLimit(2)
    once = limit.bound(gauge.fetch_service)
    assert limit.bound(once) is once
    assert CallLimit(2).bound(once) is not once
    await once("cvbd_is_decsn", volatility="medium")
    assert (gauge.calls, limit.max_in_flight) == (1, 2)


def test_a_call_limit_needs_at_least_one_slot():
    with pytest.raises(ValueError, match="at least 1"):
        CallLimit(0)
