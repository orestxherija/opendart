"""get_capital_structure: shares, treasury stock, capital changes, use of proceeds."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import CompanyArg, FiscalYearArg, PeriodArg, ResponseFormatArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.capital import CapitalSection, CapitalStructureResult
from opendart_mcp.render.capital import render_capital_structure
from opendart_mcp.services.capital import SECTIONS, CapitalQuery, capital_structure


@tool(
    name="get_capital_structure",
    version="1.0.0",
    title="Capital structure",
    tags={"capital"},
    annotations=READ_ONLY,
)
@markdown_view(render_capital_structure)
async def get_capital_structure(
    *,
    company: CompanyArg,
    sections: Annotated[
        list[CapitalSection] | None,
        Field(min_length=1, description="Sections to return; default all."),
    ] = None,
    period: PeriodArg = "latest",
    fiscal_year: FiscalYearArg = None,
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> CapitalStructureResult:
    """Show a company's share capital and how it got there, from one periodic report.

    Sections: shares (authorized, issued, treasury, and outstanding shares by class),
    treasury_stock (shares acquired, disposed of, and retired in the period),
    capital_changes (share issuances and reductions with dates, types, and prices), and
    use_of_proceeds (planned versus actual use of money raised by public offerings and
    private placements). Outstanding convertible bonds, warrants, and pending rights
    issues are events: call get_corporate_events with categories
    ["convertible_and_hybrid_debt", "capital_raise"]. Use get_ownership for holders,
    control, and the free float.

    Args:
        company (CompanyArg): Company to analyze.
        sections (list[CapitalSection] | None): Sections to return.
        period (PeriodArg): Periodic report to read.
        fiscal_year (FiscalYearArg): Fiscal year of that report.
        response_format (ResponseFormatArg): Concise or detailed output.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        CapitalStructureResult: The company's share capital, issuances, and treasury shares.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    query = CapitalQuery(
        company=company,
        sections=tuple(sections) if sections else SECTIONS,
        period=period,
        fiscal_year=fiscal_year,
        detailed=response_format == "detailed",
    )
    return await capital_structure(state, query, progress=Reporter(ctx))


TOOLS = (get_capital_structure,)
