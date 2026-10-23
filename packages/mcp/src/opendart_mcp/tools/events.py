"""get_corporate_events: material events from major-issue and registration reports."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY, TASK_OPTIONAL
from opendart_mcp.app.params import CompanyArg, ResponseFormatArg, SinceArg, UntilArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.events import CorporateEventsResult
from opendart_mcp.render.events import render_events
from opendart_mcp.services.event_results import DEFAULT_LIMIT, MAX_LIMIT, EventRequest
from opendart_mcp.services.events import BACKGROUND_DEADLINE, FOREGROUND_DEADLINE, corporate_events

CategoriesArg = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=40)]] | None,
    Field(
        min_length=1,
        max_length=42,
        description="Event groups or kinds; default: the kinds the company filed.",
    ),
]


@tool(
    name="get_corporate_events",
    version="1.0.0",
    title="Corporate events",
    tags={"events"},
    annotations=READ_ONLY,
    task=TASK_OPTIONAL,
)
@markdown_view(render_events)
async def get_corporate_events(
    *,
    company: CompanyArg,
    categories: CategoriesArg = None,
    since: SinceArg = "1y",
    until: UntilArg = None,
    limit: Annotated[
        int, Field(ge=1, le=MAX_LIMIT, description="Maximum events, newest first.")
    ] = DEFAULT_LIMIT,
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> CorporateEventsResult:
    """List a company's material events from major-issue and registration reports.

    Covers rights and bonus issues, convertible, warrant, exchangeable, and contingent
    bonds, buybacks and treasury-stock trusts, capital reductions, mergers, splits, share
    swaps, business and asset deals, defaults, rehabilitation, lawsuits, overseas listings,
    and registered offerings. Each event has a headline, normalized key terms, dated
    actions, and flags such as backdoor listing, put options, third-party allotment, and
    amendments. Without categories, the company's filing index picks the reports to read.
    Rows show the latest amended terms; the window applies to original filing dates. KRX
    disclosures such as supply contracts are in search_filings; upcoming dates across a
    watchlist are in get_corporate_action_calendar.

    Args:
        company (CompanyArg): Company whose events to list.
        categories (CategoriesArg): Event groups or kinds to read.
        since (SinceArg): Start of the original filing date window.
        until (UntilArg): End of the window.
        limit (int): Maximum number of events.
        response_format (ResponseFormatArg): concise or detailed.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        CorporateEventsResult: Material events decoded from the company's filings.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    deadline = BACKGROUND_DEADLINE if ctx.is_background_task else FOREGROUND_DEADLINE
    request = EventRequest(
        categories=tuple(categories) if categories else None,
        since=since,
        until=until,
        limit=limit,
        detailed=response_format == "detailed",
    )
    return await corporate_events(
        state, company, request=request, progress=Reporter(ctx), deadline=deadline
    )


TOOLS = (get_corporate_events,)
