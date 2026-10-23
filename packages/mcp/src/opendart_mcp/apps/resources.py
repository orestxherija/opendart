"""The app pages as ``ui://`` resources, linked from their tools' metadata.

Each page is a fixed HTML document built at import; the data arrives later, from the host, as
the linked tool's structured content. Resource metadata asks hosts to frame the page
(``prefersBorder``) and declares an empty content security policy: the page loads nothing
from any origin.
"""

from __future__ import annotations

from typing import Any, Final

from fastmcp.apps import UI_MIME_TYPE, AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources import resource

from opendart_mcp.apps.links import CALENDAR_URI, FINANCIALS_URI, PEERS_URI
from opendart_mcp.apps.pages import build_page

FINANCIALS_PAGE: Final = build_page("financials", title="OpenDART financial statements")
"""HTML of the financial statements app."""

PEERS_PAGE: Final = build_page("peers", title="OpenDART peer comparison")
"""HTML of the peer comparison app."""

CALENDAR_PAGE: Final = build_page("calendar", title="OpenDART corporate-action calendar")
"""HTML of the corporate-action calendar app."""


def page_meta() -> dict[str, Any]:
    """Build the resource metadata of an app page.

    Returns:
        dict[str, Any]: ``ui`` metadata: framed by the host, no external origins.
    """
    return {"ui": app_config_to_meta_dict(AppConfig(csp=ResourceCSP(), prefers_border=True))}


@resource(
    FINANCIALS_URI,
    name="financials_app",
    version="1.0.0",
    title="Financial statements app",
    description="Interactive view of get_financials results: statement views, three-month or year-to-date amounts, negative values highlighted.",
    mime_type=UI_MIME_TYPE,
    tags={"app"},
    meta=page_meta(),
)
async def financials_app() -> str:
    """Financial statements app page.

    Returns:
        str: HTML document.
    """
    return FINANCIALS_PAGE


@resource(
    PEERS_URI,
    name="peers_app",
    version="1.0.0",
    title="Peer comparison app",
    description="Interactive view of compare_companies results: sortable metrics, column highs and lows, companies left out, and metric sets.",
    mime_type=UI_MIME_TYPE,
    tags={"app"},
    meta=page_meta(),
)
async def peers_app() -> str:
    """Peer comparison app page.

    Returns:
        str: HTML document.
    """
    return PEERS_PAGE


@resource(
    CALENDAR_URI,
    name="calendar_app",
    version="1.0.0",
    title="Corporate-action calendar app",
    description="Interactive view of get_corporate_action_calendar results: dates by week, company and action filters, and links to the filings.",
    mime_type=UI_MIME_TYPE,
    tags={"app"},
    meta=page_meta(),
)
async def calendar_app() -> str:
    """Corporate-action calendar app page.

    Returns:
        str: HTML document.
    """
    return CALENDAR_PAGE


RESOURCES = (financials_app, peers_app, calendar_app)
