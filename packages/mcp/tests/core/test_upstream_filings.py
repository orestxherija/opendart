"""Binding paged filing searches for analysis workflows to the gateway."""

from __future__ import annotations

import datetime as dt

import pytest

from opendart_analysis.filings import FilingPageQuery
from opendart_mcp.core.ttl import FILINGS
from opendart_mcp.core.upstream_filings import filing_pages


class _Gateway:
    """Records gateway calls and answers each with a fixed response."""

    def __init__(self, sdk: object, response: object) -> None:
        self.sdk = sdk
        self.response = response
        self.calls: list[tuple[float, object, dict[str, object]]] = []

    async def call(self, ttl: float, method: object, **kwargs: object) -> object:
        self.calls.append((ttl, method, kwargs))
        return self.response


@pytest.mark.anyio
async def test_a_page_query_becomes_one_search_call_cached_like_filing_lists(sdk):
    page = object()
    gateway = _Gateway(sdk, response=page)
    read_page = filing_pages(lambda: gateway)
    query = FilingPageQuery(
        None,
        dt.date(2026, 9, 1),
        dt.date(2026, 10, 22),
        subtype="I002",
        final_only=True,
        corporation_type="K",
        page=3,
        page_size=50,
    )

    assert await read_page(query, volatility="high") is page

    [(ttl, method, kwargs)] = gateway.calls
    assert ttl == FILINGS
    assert method == sdk.disclosures.search
    assert kwargs == {
        "corporation_code": None,
        "filing_start_date": "20260901",
        "filing_end_date": "20261022",
        "final_reports_only": "Y",
        "disclosure_category": None,
        "disclosure_subcategory": "I002",
        "corporation_type": "K",
        "page_number": 3,
        "page_size": 50,
    }
