"""The events and filing-discovery guides' SDK recipes, without the SDK or MCP.

``sdk_filing_pages`` and ``sdk_service_fetch`` match the filing-discovery and events guides. A
duck-typed client stands in for ``opendart.OpenDART``, and a local ``NoDataError`` for the
SDK's exception of that name.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.catalog import service
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.events import (
    EventQuery,
    amendment_flag,
    covered_window,
    describe,
    fetch_events,
)
from opendart_analysis.filings import FilingSearchRequest, find_filings
from scripts.testing.events import convertible_bond, filing

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from opendart_analysis.filings import FilingPage, FilingPageQuery, ReadFilingPage
    from opendart_analysis.upstream import FetchService, Volatility

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
NUMBER = "20260915000123"


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


async def or_none[T](call: Awaitable[T]) -> T | None:
    try:
        return await call
    except NoDataError:
        return None


def sdk_filing_pages(client: Any) -> ReadFilingPage:
    async def read_filing_page(
        query: FilingPageQuery, /, *, volatility: Volatility
    ) -> FilingPage | None:
        del volatility  # This recipe caches nothing.
        return await or_none(
            client.disclosures.search(
                corporation_code=query.corp_code,
                filing_start_date=f"{query.start:%Y%m%d}",
                filing_end_date=f"{query.end:%Y%m%d}",
                final_reports_only="Y" if query.final_only else None,
                disclosure_category=query.group,
                disclosure_subcategory=query.subtype,
                corporation_type=query.corporation_type,
                page_number=query.page,
                page_size=query.page_size,
            )
        )

    return read_filing_page


def sdk_service_fetch(client: Any) -> FetchService:
    async def fetch_service(
        name: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        del volatility  # This recipe caches nothing.
        method = getattr(getattr(client, service(name).resource), name)
        return await or_none(method(**params))

    return fetch_service


def row(body: dict[str, str]) -> SimpleNamespace:
    """Convert a wire-format search record to the SDK's field names."""
    names = {
        "corp_cls": "corporation_type",
        "corp_name": "corporation_name",
        "corp_code": "corporation_code",
        "stock_code": "stock_code",
        "report_nm": "report_title",
        "rcept_no": "filing_number",
        "flr_nm": "submitter_name",
        "rcept_dt": "filing_date",
        "rm": "rm",
    }
    return SimpleNamespace(**{names[key]: value for key, value in body.items()})


class FakeDisclosures:
    """Answers ``disclosures.search`` like the SDK, for major-issue filings only."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(self, **params: Any) -> SimpleNamespace:
        self.calls.append(params)
        if params["disclosure_category"] not in {"B", None}:
            raise NoDataError
        rows = [
            row(filing(NUMBER, "[Corrected description]Decision on Issuance of Convertible Bonds"))
        ]
        return SimpleNamespace(list=rows, total_count=1, total_page=1)


class FakeMajorIssues:
    """Answers ``major_issues.cvbd_is_decsn`` like the SDK: a response with ``list``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def cvbd_is_decsn(self, **params: Any) -> SimpleNamespace:
        self.calls.append(params)
        return SimpleNamespace(list=[convertible_bond(NUMBER)])


async def test_the_recipes_read_interpreted_events_and_filings():
    client = SimpleNamespace(disclosures=FakeDisclosures(), major_issues=FakeMajorIssues())
    window = covered_window(DateWindow(dt.date(2025, 10, 22), TODAY), today=TODAY)
    assert window is not None
    batch = await fetch_events(
        EventQuery("00126380", window, name="Samsung Electronics"),
        fetch_service=sdk_service_fetch(client),
        read_filing_page=sdk_filing_pages(client),
    )
    (record,) = batch.records
    view = describe(record)
    assert (batch.strategy, batch.queried) == ("filing_index", ("convertible_bond",))
    assert amendment_flag(view, batch.titles()) == "amended"
    assert client.major_issues.calls == [
        {
            "corporation_code": "00126380",
            "filing_start_date": "20251022",
            "filing_end_date": "20261022",
        }
    ]

    request = FilingSearchRequest("00126380", window, categories=("major_issues",))
    results = await find_filings(request, read_page=sdk_filing_pages(client))
    (found,) = results.filings
    assert (found.filing_number, found.category, found.is_amendment) == (
        NUMBER,
        "major_issues",
        True,
    )
    assert client.disclosures.calls[-1]["final_reports_only"] == "Y"
