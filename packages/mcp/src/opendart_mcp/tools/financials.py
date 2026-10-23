"""get_financials: every financial statement view for one company."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import (
    BasisArg,
    CompanyArg,
    FiscalYearArg,
    PeriodArg,
    ResponseFormatArg,
    UnitArg,
)
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.apps.links import FINANCIALS_URI, app_link
from opendart_mcp.core.state import AppState
from opendart_mcp.models.financials import FinancialView, FinancialsResult
from opendart_mcp.render.financials import render_financials
from opendart_mcp.services.financials import FinancialsRequest, financials


@tool(
    name="get_financials",
    version="1.0.0",
    title="Financial statements",
    tags={"financials"},
    annotations=READ_ONLY,
    meta=app_link(FINANCIALS_URI),
)
@markdown_view(render_financials)
async def get_financials(
    *,
    company: CompanyArg,
    view: Annotated[
        FinancialView,
        Field(description="summary, a full statement, ratios, equity_investments, or preliminary."),
    ] = "summary",
    basis: BasisArg = "auto",
    period: PeriodArg = "latest",
    fiscal_year: FiscalYearArg = None,
    years: Annotated[
        int,
        Field(ge=1, le=5, description="Reports to chain back; one annual report spans 3 years."),
    ] = 1,
    accounts: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=80)]] | None,
        Field(max_length=20, description="Keep lines whose account name contains any of these."),
    ] = None,
    unit: UnitArg = "million_krw",
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> FinancialsResult:
    """Get one company's financial statements as a table of line items by period.

    Views: summary (major accounts plus derived growth, margins, and leverage), income,
    balance, cash_flow, comprehensive_income, and equity_changes (full statements, key lines
    first; accounts filters by name), ratios (OpenDART's profitability, stability, growth,
    and activity indicators, from fiscal 2022), equity_investments (stakes in other
    companies at book value), and preliminary (the latest unaudited quarterly results from a
    KRX fair disclosure). One annual report holds three fiscal years. Quarterly income lines
    show three-month and year-to-date amounts. Use compare_companies for peer tables. Data
    starts in 2015; there are no prices.

    Args:
        company (CompanyArg): Company to report on.
        view (FinancialView): Statement view.
        basis (BasisArg): Consolidated or separate statements; auto prefers consolidated.
        period (PeriodArg): Reporting period.
        fiscal_year (FiscalYearArg): Fiscal year; default the latest with the period.
        years (int): Reports to chain backwards.
        accounts (list[str] | None): Substring filters on account names.
        unit (UnitArg): Unit for amounts in the text table.
        response_format (ResponseFormatArg): Concise or detailed output.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        FinancialsResult: The requested financial statement or indicator view.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    request = FinancialsRequest(
        view=view,
        basis=basis,
        period=period,
        fiscal_year=fiscal_year,
        years=years,
        accounts=tuple(accounts) if accounts else None,
        unit=unit,
        response_format=response_format,
    )
    return await financials(state, company, request, progress=Reporter(ctx))


TOOLS = (get_financials,)
