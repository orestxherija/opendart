"""Resolve requested periods to the fiscal year and report code OpenDART expects.

The logic lives in ``opendart_analysis.reports``. This adapter binds it to the gateway and
the server clock and turns its exceptions into server errors with unchanged messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis import reports
from opendart_analysis.errors import AnalysisError
from opendart_mcp.core.errors import from_analysis
from opendart_mcp.core.upstream import filing_search

if TYPE_CHECKING:
    from opendart_analysis.domain.types import Period
    from opendart_analysis.reports import ResolvedPeriod
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company


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
