"""search_filings: the filing index, by company or market-wide."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import PageArg, SinceArg, UntilArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.domain.categories import FilingCategory
from opendart_mcp.domain.types import MarketFilter
from opendart_mcp.models.filings import SearchFilingsResult
from opendart_mcp.render.filings import render_search_filings
from opendart_mcp.services.filings import DEFAULT_LIMIT, DEFAULT_SINCE, FilingSearch, find_filings

OptionalCompanyArg = Annotated[
    str | None,
    Field(
        min_length=1,
        max_length=100,
        description="Company name, stock code, or corp code; omit to search every company.",
    ),
]


@tool(
    name="search_filings",
    version="1.0.0",
    title="Search filings",
    tags={"filings"},
    annotations=READ_ONLY,
)
@markdown_view(render_search_filings)
async def search_filings(
    *,
    company: OptionalCompanyArg = None,
    categories: Annotated[
        list[FilingCategory] | None,
        Field(
            min_length=1,
            max_length=10,
            description="Filing categories; default all (opendart://reference/filing-categories).",
        ),
    ] = None,
    since: SinceArg = DEFAULT_SINCE,
    until: UntilArg = None,
    market: Annotated[
        MarketFilter, Field(description="Restrict to a listing market, or to unlisted companies.")
    ] = "all",
    title_contains: Annotated[
        str | None,
        Field(min_length=2, max_length=100, description="Text the English title must contain."),
    ] = None,
    final_only: Annotated[
        bool, Field(description="Only the latest version of amended filings.")
    ] = True,
    limit: Annotated[int, Field(ge=1, le=100, description="Filings per page.")] = DEFAULT_LIMIT,
    page: PageArg = 1,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> SearchFilingsResult:
    """List filings newest first, for one company or the whole market: what was filed.

    Filter by category (annual_report, major_issues, major_holding_report, fair_disclosure,
    and others), date window, listing market, and title text. Use it to see what a company
    filed recently, to scan the market for one kind of filing, and to find filing numbers
    for read_filing. KRX ad hoc and fair disclosures, such as supply contracts, guidance,
    and preliminary earnings, are reachable only here and through read_filing. Without a
    company the window is limited to three months. title_contains scans a bounded number
    of the newest filings and says when it could not cover the whole window. For the
    decoded terms of capital raises, convertible bonds, buybacks, or mergers, use
    get_corporate_events.

    Args:
        company (OptionalCompanyArg): Company to search; omit for every company.
        categories (list[FilingCategory] | None): Categories to include.
        since (SinceArg): Window start.
        until (UntilArg): Window end.
        market (MarketFilter): Listing market filter.
        title_contains (str | None): Case-insensitive title text.
        final_only (bool): Exclude superseded versions of amended filings.
        limit (int): Filings per page.
        page (PageArg): Page number.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        SearchFilingsResult: Matching filings and their pagination details.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    search = FilingSearch(
        company=company,
        categories=tuple(categories or ()),
        since=since,
        until=until,
        market=market,
        title_contains=title_contains,
        final_only=final_only,
        limit=limit,
        page=page,
    )
    return await find_filings(state, search, progress=Reporter(ctx))


TOOLS = (search_filings,)
