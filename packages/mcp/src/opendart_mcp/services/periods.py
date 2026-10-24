"""Resolve requested periods to the fiscal year and report code OpenDART expects.

The logic lives in ``opendart_analysis.reports``. This adapter binds it to the gateway and
the server clock, maps period volatility to cache lifetimes, and turns its exceptions into
server errors with unchanged messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis import reports
from opendart_analysis.errors import AnalysisError
from opendart_analysis.reports import (
    PROBE_ATTEMPTS,
    PeriodicReport,
    ResolvedPeriod,
    first_available,
    period_volatility,
)
from opendart_mcp.core.errors import from_analysis
from opendart_mcp.core.ttl import lifetime
from opendart_mcp.core.upstream import filing_search

if TYPE_CHECKING:
    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Period
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company

__all__ = [
    "PROBE_ATTEMPTS",
    "PeriodicReport",
    "ResolvedPeriod",
    "first_available",
    "latest_periodic_report",
    "periodic_ttl",
    "resolve_period",
]


async def latest_periodic_report(
    state: AppState, company: Company, period: Period = "latest"
) -> PeriodicReport | None:
    """Find the company's most recent final periodic report.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        period (Period): ``latest`` for any kind, or one period.

    Returns:
        PeriodicReport | None: Newest matching report from the last 15 months, if any.

    Raises:
        ConfigurationError: No API key is configured.
    """
    return await reports.latest_periodic_report(
        company, period, search_filings=filing_search(state.require_gateway), today=state.today()
    )


async def resolve_period(
    state: AppState, company: Company, *, period: Period, fiscal_year: int | None
) -> ResolvedPeriod:
    """Turn a requested period into candidates to probe.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        period (Period): Requested period.
        fiscal_year (int | None): Requested fiscal year, if any.

    Returns:
        ResolvedPeriod: Candidates, best first.

    Raises:
        InvalidArgumentError: The requested period has not ended yet or predates 2015.
    """
    try:
        return await reports.resolve_period(
            company,
            period=period,
            fiscal_year=fiscal_year,
            search_filings=filing_search(state.require_gateway),
            today=state.today(),
        )
    except AnalysisError as error:
        raise from_analysis(error) from error


def periodic_ttl(state: AppState, company: Company, ref: PeriodRef) -> float:
    """Choose how long to cache a period's periodic-report or statement data.

    Data for a period still inside its filing window is cached only as long as filing lists;
    afterwards it is cached for a day (see ``opendart_analysis.reports.period_volatility``).

    Args:
        state (AppState): Server state.
        company (Company): Resolved company (its fiscal year-end month sets the deadline).
        ref (PeriodRef): Period being fetched.

    Returns:
        float: Cache lifetime in seconds.
    """
    return lifetime(period_volatility(ref, fye_month=company.fye_month, today=state.today()))
