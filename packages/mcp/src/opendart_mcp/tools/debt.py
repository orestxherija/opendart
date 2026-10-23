"""get_debt_profile: maturity ladder and issuance record of debt securities."""

from __future__ import annotations

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import CompanyArg, FiscalYearArg, PeriodArg, ResponseFormatArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.debt import DebtProfileResult
from opendart_mcp.render.debt import render_debt_profile
from opendart_mcp.services.debt import debt_profile


@tool(
    name="get_debt_profile",
    version="1.0.0",
    title="Debt profile",
    tags={"credit"},
    annotations=READ_ONLY,
)
@markdown_view(render_debt_profile)
async def get_debt_profile(
    *,
    company: CompanyArg,
    period: PeriodArg = "latest",
    fiscal_year: FiscalYearArg = None,
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> DebtProfileResult:
    """Show a company's debt securities from a periodic report, for credit and refinancing.

    Returns a maturity ladder of outstanding corporate bonds, short-term bonds, commercial
    paper, hybrid securities, and contingent capital securities in common remaining-maturity
    buckets, the share due within a year, and the issuance record with coupons, ratings,
    maturities, and redemption status. Concise output lists only issues not fully redeemed.
    Bank loans and total borrowings are in get_financials; newly decided convertible or
    other bond issues are in get_corporate_events. Balances are as of the report's period
    end and may cover only the filing company, not its subsidiaries.

    Args:
        company (CompanyArg): Company to analyze.
        period (PeriodArg): Reporting period.
        fiscal_year (FiscalYearArg): Fiscal year of the period.
        response_format (ResponseFormatArg): Level of detail.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        DebtProfileResult: The company's debt securities and maturity profile.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    return await debt_profile(
        state,
        company,
        period=period,
        fiscal_year=fiscal_year,
        response_format=response_format,
        progress=Reporter(ctx),
    )


TOOLS = (get_debt_profile,)
