"""get_dividends: dividend history by share class and fiscal year."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import CompanyArg, ResponseFormatArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.dividends import DividendsResult
from opendart_mcp.render.dividends import render_dividends
from opendart_mcp.services.dividends import dividends


@tool(
    name="get_dividends",
    version="1.0.0",
    title="Dividend history",
    tags={"capital"},
    annotations=READ_ONLY,
)
@markdown_view(render_dividends)
async def get_dividends(
    *,
    company: CompanyArg,
    years: Annotated[
        int, Field(ge=1, le=10, description="Fiscal years of history; each call covers three.")
    ] = 3,
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> DividendsResult:
    """Get a company's dividend history from its annual reports, by share class and fiscal year.

    Returns cash and stock dividends per share for common and preferred shares, total
    payout, the payout ratio, dividend yield, and the net income and EPS the payout is
    based on, with consolidated or separate basis marked. One annual report covers three
    fiscal years, so longer histories cost more upstream calls. Yields are as filed by the
    company; OpenDART has no market prices. Dividends decided after the latest annual
    report are not included: search_filings finds new dividend decisions.

    Args:
        company (CompanyArg): Company to analyze.
        years (int): Number of fiscal years, newest first.
        response_format (ResponseFormatArg): Level of detail.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        DividendsResult: Dividend history by share class and fiscal year.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    return await dividends(
        state, company, years=years, response_format=response_format, progress=Reporter(ctx)
    )


TOOLS = (get_dividends,)
