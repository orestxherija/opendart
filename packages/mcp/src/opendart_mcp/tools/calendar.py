"""get_corporate_action_calendar: forward corporate-action dates for a company or watchlist."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY, TASK_OPTIONAL
from opendart_mcp.app.params import CompaniesArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.apps.links import CALENDAR_URI, app_link
from opendart_mcp.core.state import AppState
from opendart_mcp.models.calendar import CalendarResult
from opendart_mcp.render.calendar import render_calendar
from opendart_mcp.services.calendar import CalendarRequest, action_calendar
from opendart_mcp.services.calendar_debt import debt_maturities
from opendart_mcp.services.events import BACKGROUND_DEADLINE, FOREGROUND_DEADLINE

KindsArg = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=40)]] | None,
    Field(
        min_length=1,
        max_length=42,
        description="Event groups or kinds, or debt_maturity; default: all kinds with dates.",
    ),
]


@tool(
    name="get_corporate_action_calendar",
    version="1.0.1",
    title="Corporate-action calendar",
    tags={"events"},
    annotations=READ_ONLY,
    meta=app_link(CALENDAR_URI),
    task=TASK_OPTIONAL,
)
@markdown_view(render_calendar)
async def get_corporate_action_calendar(
    *,
    companies: CompaniesArg,
    horizon: Annotated[
        str,
        Field(min_length=2, max_length=10, description="Last date: ISO date or 30d, 6m, 1y."),
    ] = "90d",
    include_past: Annotated[
        str | None,
        Field(min_length=2, max_length=10, description="Also show dates since: date or 30d."),
    ] = None,
    kinds: KindsArg = None,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> CalendarResult:
    """Get upcoming corporate-action dates for one company or a watchlist, sorted by date.

    Covers subscription and payment dates, record dates, new-share listings, conversion,
    warrant, and exchange windows, short-sale restrictions around rights issues, buyback
    and disposal periods, shareholder meetings, dissent and appraisal-rights windows,
    trading suspensions, merger or split effective dates, and bond maturities. Dates come
    from major-issue and registration filings of the past year (three years for bond
    filings), with the latest amended terms. Debt maturities from periodic reports list
    only recently issued securities; a note gives corporate bonds due within a year.
    horizon counts forward from today; include_past adds recent dates. Use
    get_corporate_events for full deal terms and get_debt_profile for the full ladder.

    Args:
        companies (CompaniesArg): Companies to cover.
        horizon (str): Last date to include.
        include_past (str | None): First date when earlier than today.
        kinds (KindsArg): Event groups or kinds to include.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        CalendarResult: Corporate-action dates and debt maturities for the requested companies.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    deadline = BACKGROUND_DEADLINE if ctx.is_background_task else FOREGROUND_DEADLINE
    request = CalendarRequest(
        horizon=horizon, include_past=include_past, kinds=tuple(kinds) if kinds else None
    )
    return await action_calendar(
        state,
        companies,
        request=request,
        progress=Reporter(ctx),
        deadline=deadline,
        maturities=debt_maturities,
    )


TOOLS = (get_corporate_action_calendar,)
