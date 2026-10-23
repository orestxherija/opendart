"""Company identity tools: find_company and get_company_profile."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import CompanyArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.domain.types import MarketFilter
from opendart_mcp.models.company import CompanyProfileResult, FindCompanyResult
from opendart_mcp.render.company import render_find_company, render_profile
from opendart_mcp.services.profile import company_profile, find_companies


@tool(
    name="find_company",
    version="1.0.0",
    title="Find a company",
    tags={"identity"},
    annotations=READ_ONLY,
)
@markdown_view(render_find_company)
async def find_company(
    *,
    query: Annotated[
        str,
        Field(min_length=1, max_length=100, description="Name (English or Korean), or a code."),
    ],
    market: Annotated[
        MarketFilter, Field(description="Restrict to a market, or to unlisted companies.")
    ] = "all",
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum matches.")] = 10,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> FindCompanyResult:
    """Search the DART company directory by name or code and list ranked matches.

    Every other tool already accepts a company name, stock code, or DART corp code and
    resolves it, so call this only to confirm an identity, browse similarly named
    companies, or pick among candidates after an ambiguity error. Matching tries exact
    codes, then exact names in English or Korean, then prefixes, words, and close
    spellings, with listed companies first. best_match is set only when one candidate
    clearly dominates. Markets are filled in when filtering by market.

    Args:
        query (str): Company name or code to look up.
        market (MarketFilter): Market filter.
        limit (int): Maximum number of matches.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        FindCompanyResult: Ranked company matches and the dominant match, if any.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    return await find_companies(state, query, market=market, limit=limit, progress=Reporter(ctx))


@tool(
    name="get_company_profile",
    version="1.0.0",
    title="Company profile",
    tags={"identity"},
    annotations=READ_ONLY,
)
@markdown_view(render_profile)
async def get_company_profile(
    *,
    company: CompanyArg,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> CompanyProfileResult:
    """Get a company's identity, reference facts, and latest periodic report.

    Returns names in English and Korean, stock and DART codes, listing market, CEO,
    industry code, fiscal year-end month, establishment date, address, and websites,
    plus the most recent annual, half-year, or quarterly report, which is what
    period="latest" means in the financial and periodic-report tools.

    Args:
        company (CompanyArg): Company to profile.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        CompanyProfileResult: Company identity, reference facts, and latest periodic report.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    return await company_profile(state, company, progress=Reporter(ctx))


TOOLS = (find_company, get_company_profile)
