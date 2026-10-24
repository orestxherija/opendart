"""Fetch and read periodic-report extracts: one service, one company, one reporting period.

The logic lives in ``opendart_analysis.extracts``. This adapter binds fetching to the gateway
and the server clock (the period's volatility maps to the same lifetimes as ``periodic_ttl``),
projects filing provenance to ``SourceFiling``, and turns analysis exceptions into server
errors with unchanged messages. Field readers are the analysis functions themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis import extracts
from opendart_analysis.errors import AnalysisError
from opendart_analysis.extracts import (
    checked,
    filed_text,
    fold,
    is_total,
    probe_attempts,
    records,
    term_ages,
    text,
)
from opendart_mcp.core.errors import from_analysis
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.models.common import SourceFiling

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable

    from opendart_analysis.reports import PeriodRef, PeriodicReport
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company

__all__ = [
    "checked",
    "fetch_records",
    "fetch_response",
    "filed_text",
    "fold",
    "gather_all",
    "is_total",
    "probe_attempts",
    "records",
    "sources",
    "term_ages",
    "text",
]


async def fetch_response(
    state: AppState, service: str, *, company: Company, ref: PeriodRef
) -> object | None:
    """Call one periodic-report service for a company and period, through the cache.

    Answers for a period whose filing deadline has not settled are cached only briefly, so
    a report filed or corrected meanwhile is picked up; settled periods are cached a day.

    Args:
        state (AppState): Server state.
        service (str): SDK method name, such as ``alot_matter``.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        object | None: SDK response model, or None when OpenDART has no data.
    """
    return await extracts.fetch_response(
        service,
        company=company,
        ref=ref,
        fetch_service=service_fetch(state.require_gateway),
        today=state.today(),
    )


async def fetch_records(
    state: AppState, service: str, *, company: Company, ref: PeriodRef
) -> list[object] | None:
    """Fetch one periodic-report service's ``list`` records for a company and period.

    Args:
        state (AppState): Server state.
        service (str): SDK method name.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        list[object] | None: Records, or None when OpenDART has no data.
    """
    response = await fetch_response(state, service, company=company, ref=ref)
    return None if response is None else records(response)


async def gather_all[T](calls: Iterable[Awaitable[T]]) -> list[T]:
    """Await calls concurrently and return their results in order.

    Every call runs to completion so each answer reaches the cache; then the first failure,
    if any, is raised unwrapped so its actionable message survives. An analysis failure
    becomes the server error for its category.

    Args:
        calls (Iterable[Awaitable[T]]): Calls to await.

    Returns:
        list[T]: Results in call order.

    Raises:
        ServerError: An analysis failure among the calls, translated.
        Exception: Any other first failure among the calls, unchanged.
    """
    try:
        return await extracts.gather_all(calls)
    except AnalysisError as error:
        raise from_analysis(error) from error


def sources(
    numbers: Iterable[str | None], report: PeriodicReport | None = None
) -> list[SourceFiling]:
    """Describe the filings that records came from, in order of first appearance.

    Args:
        numbers (Iterable[str | None]): Filing numbers from records; invalid ones are skipped.
        report (PeriodicReport | None): Report found in the filing index, for its title.

    Returns:
        list[SourceFiling]: Provenance entries.
    """
    return [
        SourceFiling.of(source.filing_number, source.title)
        for source in extracts.sources(numbers, report)
    ]
