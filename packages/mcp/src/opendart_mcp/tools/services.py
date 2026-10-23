"""list_services and call_service: escape hatches, registered only when enabled."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import PageArg, ResponseFormatArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.services import ParamValue, ServiceCallResult, ServiceListResult
from opendart_mcp.render.services import render_service_call, render_service_list
from opendart_mcp.services.catalog import Page, call_service as call, list_services as search


@tool(
    name="list_services",
    version="1.0.0",
    title="List OpenDART services",
    tags={"escape-hatch"},
    annotations=READ_ONLY,
)
@markdown_view(render_service_list)
async def list_services(
    *,
    query: Annotated[
        str | None,
        Field(max_length=100, description="Keywords such as 'convertible bond'; omit to list all."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=85, description="Maximum services.")] = 10,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> ServiceListResult:
    """Search OpenDART's upstream services for call_service. A last resort.

    Every service is already served by a topical tool that resolves companies and
    periods and labels its results, and each match names that tool under covered_by;
    prefer it. Use this only when no other tool returns the data you need, such as a
    field the topical tools omit. Matching uses words from service titles and
    descriptions plus shorthand such as CB, BW, or buyback; without a query every
    callable service is listed. Results show each parameter and the values it accepts.

    Args:
        query (str | None): Keywords to match.
        limit (int): Maximum services to return.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        ServiceListResult: Matching callable OpenDART services and their parameters.

    """
    del ctx
    return search(state, query, limit=limit)


@tool(
    name="call_service",
    version="1.0.0",
    title="Call an OpenDART service",
    tags={"escape-hatch"},
    annotations=READ_ONLY,
)
@markdown_view(render_service_call)
async def call_service(
    *,
    service: Annotated[
        str,
        Field(min_length=1, max_length=80, description="Service name from list_services."),
    ],
    params: Annotated[
        dict[str, ParamValue] | None,
        Field(description='Parameters by name, such as {"corp_code": "Samsung Electronics"}.'),
    ] = None,
    response_format: ResponseFormatArg = "concise",
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum rows per page.")] = 20,
    page: PageArg = 1,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> ServiceCallResult:
    """Call one OpenDART service directly and return its records, labeled and normalized.

    A last resort for data no other tool returns: find the service and its parameters
    with list_services first. Parameters take the names list_services shows or the
    upstream names. Company parameters also take names and stock codes, dates take ISO
    or relative forms such as 90d, and report codes take FY, H1, Q1, or Q3. Amounts are
    exact won, percentages are percent units, and dates are ISO. Concise output drops
    empty columns and lists values shared by every row once; detailed output keeps every
    field and adds the upstream text. Archive downloads are not available.

    Args:
        service (str): SDK method name, upstream API ID, or endpoint.
        params (dict[str, ParamValue] | None): Parameter values by name.
        response_format (ResponseFormatArg): Output detail.
        limit (int): Maximum rows per page.
        page (PageArg): Page of rows.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        ServiceCallResult: Normalized records returned by the requested OpenDART service.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    return await call(
        state,
        service,
        params,
        response_format=response_format,
        page=Page(page, limit),
        progress=Reporter(ctx),
    )


TOOLS = (list_services, call_service)
