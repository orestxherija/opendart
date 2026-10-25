"""Bind paged filing-search access for analysis workflows to the gateway.

Like ``core.upstream``, the factory returns a callable that reaches the gateway only when
called and maps the workflow's volatility to a cache lifetime with ``core.ttl.lifetime``. Its
return annotation names the analysis Protocol, so the type check proves that the SDK's
search pages satisfy it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from opendart_analysis.domain.dates import yyyymmdd
from opendart_mcp.core.ttl import lifetime

if TYPE_CHECKING:
    from collections.abc import Callable

    from opendart_analysis.filings import FilingPage, FilingPageQuery, ReadFilingPage
    from opendart_analysis.upstream import Volatility
    from opendart_mcp.core.gateway import Gateway


def filing_pages(gateway: Callable[[], Gateway]) -> ReadFilingPage:
    """Read pages of ``disclosures.search`` through the gateway.

    Args:
        gateway (Callable[[], Gateway]): Returns the gateway or raises the configuration
            error, such as ``state.require_gateway``.

    Returns:
        ReadFilingPage: Paged filing search for analysis workflows.
    """

    async def read_filing_page(
        query: FilingPageQuery, /, *, volatility: Volatility
    ) -> FilingPage | None:
        """Read one page of filings, newest first.

        Args:
            query (FilingPageQuery): Filters, window, and page.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            FilingPage | None: The SDK page, or None for OpenDART status 013.
        """
        upstream = gateway()
        return await upstream.call(
            lifetime(volatility),
            upstream.sdk.disclosures.search,
            corporation_code=query.corp_code,
            filing_start_date=yyyymmdd(query.start),
            filing_end_date=yyyymmdd(query.end),
            final_reports_only="Y" if query.final_only else None,
            disclosure_category=query.group,
            # Subtype codes are text in analysis; a test checks them against the SDK tables.
            disclosure_subcategory=cast("Any", query.subtype),
            corporation_type=query.corporation_type,
            page_number=query.page,
            page_size=query.page_size,
        )

    return read_filing_page
