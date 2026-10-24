"""The company's filing index, used to decide which event services to call.

The index lives in ``opendart_analysis.events.index``; this adapter binds its filing search
to the gateway, cached as long as filing lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis.events import index
from opendart_analysis.events.index import (
    GROUP_RESOURCES,
    INDEX_GROUPS,
    PAGE_SIZE,
    EventIndex,
    IndexGroup,
    IndexedFiling,
)
from opendart_mcp.core.upstream_filings import filing_pages

if TYPE_CHECKING:
    from opendart_analysis.domain.dates import DateWindow
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company

MAX_PAGES: Final = 3
"""Pages read per group; beyond them every kind of the group is read instead."""

__all__ = [
    "GROUP_RESOURCES",
    "INDEX_GROUPS",
    "MAX_PAGES",
    "PAGE_SIZE",
    "EventIndex",
    "IndexGroup",
    "IndexedFiling",
    "search_index",
]


async def search_index(state: AppState, company: Company, window: DateWindow) -> EventIndex:
    """Search a company's major-issue and offering filings in a window.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Filing date window.

    Returns:
        EventIndex: Filings found and whether the index is complete.
    """
    return await index.search_index(
        company.corp_code,
        window,
        read_page=filing_pages(state.require_gateway),
        max_pages=MAX_PAGES,
    )
