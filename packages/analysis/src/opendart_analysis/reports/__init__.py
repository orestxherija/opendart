"""Periodic reports: find the latest one and resolve requested periods to probe.

A request names a period (``latest``, ``FY``, ``Q1``, ``H1``, or ``Q3``) and optionally a
fiscal year. ``resolve_period`` turns it into candidate ``PeriodRef`` values, best first, using
the company's filing index when it can and statutory filing deadlines otherwise;
``first_available`` probes them until one has data:

    resolved = await resolve_period(
        company, period="latest", fiscal_year=None, search_filings=search, today=today_kst()
    )
    found = await first_available(resolved, fetch_statements)

Data access and the clock are explicit inputs, following ``opendart_analysis.upstream``.
Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.domain.dates import today_kst
from opendart_analysis.domain.periods import PeriodRef, PeriodicTitle
from opendart_analysis.domain.types import ConcretePeriod, Period
from opendart_analysis.reports.periodic import (
    PROBE_ATTEMPTS,
    FiscalCompany,
    PeriodUnavailableError,
    PeriodicReport,
    ResolvedPeriod,
    first_available,
    latest_periodic_report,
    period_volatility,
    resolve_period,
)

__all__ = [
    "PROBE_ATTEMPTS",
    "ConcretePeriod",
    "FiscalCompany",
    "Period",
    "PeriodRef",
    "PeriodUnavailableError",
    "PeriodicReport",
    "PeriodicTitle",
    "ResolvedPeriod",
    "first_available",
    "latest_periodic_report",
    "period_volatility",
    "resolve_period",
    "today_kst",
]
