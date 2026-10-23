"""get_ownership: control, holders, and insider activity."""

from __future__ import annotations

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import (
    CompanyArg,
    FiscalYearArg,
    PeriodArg,
    ResponseFormatArg,
    SinceArg,
)
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.ownership import OwnershipResult
from opendart_mcp.render.ownership import render_ownership
from opendart_mcp.services.ownership import OwnershipQuery, ownership


@tool(
    name="get_ownership",
    version="1.0.0",
    title="Ownership and control",
    tags={"ownership"},
    annotations=READ_ONLY,
)
@markdown_view(render_ownership)
async def get_ownership(
    *,
    company: CompanyArg,
    activity_window: SinceArg = "180d",
    period: PeriodArg = "latest",
    fiscal_year: FiscalYearArg = None,
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> OwnershipResult:
    """Map who controls a company and who has been trading its shares.

    From the periodic report: the largest shareholder and related parties with stakes at
    the start and end of the period, the controlling group's total, minority shareholders,
    treasury shares, a free-float estimate, and changes of the largest shareholder. From
    filings in activity_window: 5% holder reports and executive and major-shareholder
    ownership reports, newest first, with counts of increases and decreases. Percentages
    are of the class's issued shares as filed. Use get_capital_structure for share counts
    by class and treasury stock movements, and search_filings to list every holding report.

    Args:
        company (CompanyArg): Company to analyze.
        activity_window (SinceArg): Start of the window for 5% holder and insider reports.
        period (PeriodArg): Periodic report for the control snapshot.
        fiscal_year (FiscalYearArg): Fiscal year of that report.
        response_format (ResponseFormatArg): Concise or detailed output.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        OwnershipResult: Major-holder and insider ownership reports for the requested window.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    query = OwnershipQuery(
        company=company,
        activity_window=activity_window,
        period=period,
        fiscal_year=fiscal_year,
        detailed=response_format == "detailed",
    )
    return await ownership(state, query, progress=Reporter(ctx))


TOOLS = (get_ownership,)
