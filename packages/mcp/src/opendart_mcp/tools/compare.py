"""compare_companies: peer tables from the multi-company services."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import (
    BasisArg,
    CompaniesArg,
    FiscalYearArg,
    PeriodArg,
    ResponseFormatArg,
    UnitArg,
)
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.apps.links import PEERS_URI, app_link
from opendart_mcp.core.state import AppState
from opendart_mcp.models.compare import CompareMetrics, CompareResult
from opendart_mcp.render.compare import render_compare
from opendart_mcp.services.compare import CompareRequest, compare_companies as build_peers


@tool(
    name="compare_companies",
    version="1.0.0",
    title="Compare companies",
    tags={"financials"},
    annotations=READ_ONLY,
    meta=app_link(PEERS_URI),
)
@markdown_view(render_compare)
async def compare_companies(
    *,
    companies: CompaniesArg,
    metrics: Annotated[
        CompareMetrics,
        Field(
            description="key_accounts (with derived margins), ratios (OpenDART indicators), or both."
        ),
    ] = "key_accounts",
    fiscal_year: FiscalYearArg = None,
    period: PeriodArg = "FY",
    basis: BasisArg = "consolidated",
    unit: UnitArg = "million_krw",
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> CompareResult:
    """Compare up to 20 companies side by side for one fiscal period.

    key_accounts shows revenue, operating and net profit, assets, liabilities, and equity
    with derived growth, margins, and debt-to-equity; ratios shows OpenDART's published
    profitability, stability, growth, and activity indicators (from fiscal 2022); both
    combines them. Without fiscal_year the newest period with data for most companies is
    used. Companies that cannot be resolved or have no data are listed in missing instead
    of failing the call. Use get_financials for one company's full statements or several
    years.

    Args:
        companies (CompaniesArg): Companies to compare.
        metrics (CompareMetrics): Metric set.
        fiscal_year (FiscalYearArg): Fiscal year; default the latest with data.
        period (PeriodArg): Reporting period.
        basis (BasisArg): Consolidated or separate statements; auto prefers consolidated.
        unit (UnitArg): Unit for amounts in the text table.
        response_format (ResponseFormatArg): Concise or detailed output.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        CompareResult: Comparable financial rows for the requested companies and period.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    request = CompareRequest(
        metrics=metrics,
        fiscal_year=fiscal_year,
        period=period,
        basis=basis,
        unit=unit,
        response_format=response_format,
    )
    return await build_peers(state, companies, request, progress=Reporter(ctx))


TOOLS = (compare_companies,)
