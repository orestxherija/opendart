"""Bind analysis data access to the gateway.

Each factory returns a callable that satisfies one ``opendart_analysis.upstream`` Protocol. It
reaches the gateway only when called, so a keyless server raises the "configure the API key"
error at the first upstream call, as services do, and maps the workflow's volatility to a cache
lifetime with ``core.ttl.lifetime``. Return annotations name the analysis record Protocols, so
the type check proves that the SDK's records satisfy them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis.domain.dates import yyyymmdd
from opendart_mcp.core.sdk_binding import sdk_method
from opendart_mcp.core.ttl import lifetime

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from opendart_analysis.upstream import (
        FetchService,
        FilingQuery,
        FilingRecord,
        SearchFilings,
        Volatility,
    )
    from opendart_mcp.core.gateway import Gateway


def filing_search(gateway: Callable[[], Gateway]) -> SearchFilings:
    """Search filings with ``disclosures.search`` through the gateway.

    Args:
        gateway (Callable[[], Gateway]): Returns the gateway or raises the configuration
            error, such as ``state.require_gateway``.

    Returns:
        SearchFilings: Filing search for analysis workflows.
    """

    async def search_filings(
        query: FilingQuery, /, *, volatility: Volatility
    ) -> Sequence[FilingRecord] | None:
        """Read one page of filings, newest first.

        Args:
            query (FilingQuery): Company, filing-date window, and filters.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[FilingRecord] | None: SDK list records, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.disclosures.search,
            corporation_code=query.corp_code,
            filing_start_date=yyyymmdd(query.start),
            filing_end_date=yyyymmdd(query.end),
            disclosure_category=query.group,
            final_reports_only="Y" if query.final_only else None,
            page_size=query.limit,
        )
        return None if response is None else response.list

    return search_filings


def service_fetch(gateway: Callable[[], Gateway]) -> FetchService:
    """Call catalog services by SDK method name through the gateway.

    Args:
        gateway (Callable[[], Gateway]): Returns the gateway or raises the configuration
            error, such as ``state.require_gateway``.

    Returns:
        FetchService: Service calls for analysis workflows.
    """

    async def fetch_service(
        service: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        """Call one service.

        Args:
            service (str): SDK method name, such as ``alot_matter``.
            volatility (Volatility): How quickly the answer can change.
            **params (str | None): Request parameters by SDK name.

        Returns:
            object | None: The SDK response model, or None for OpenDART status 013.
        """
        upstream = gateway()
        return await upstream.call(
            lifetime(volatility), sdk_method(upstream.sdk, service), **params
        )

    return fetch_service
