"""Filing discovery over a synthetic paged index: slices, merges, title scans, and budgets."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

import pytest

from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.filings import (
    FilingPageQuery,
    FilingSearchRequest,
    SearchBudgetError,
    find_filings,
)

pytestmark = pytest.mark.anyio

WINDOW = DateWindow(dt.date(2026, 10, 1), dt.date(2026, 10, 22))


@dataclass(frozen=True)
class Row:
    """A filing-search row with the SDK's field names."""

    filing_number: str | None
    report_title: str | None = "Report on Major Issues"
    corporation_code: str | None = "00164779"
    corporation_name: str | None = "SK hynix"
    stock_code: str | None = "000660"
    corporation_type: str | None = "Y"
    submitter_name: str | None = "SK하이닉스"
    filing_date: str | None = None
    rm: str | None = ""


def row(number: str, title: str = "Report on Major Issues", **fields: str | None) -> Row:
    return Row(number, title, **{"filing_date": number[:8], **fields})


@dataclass(frozen=True)
class Page:
    list: list[Row] | None
    total_count: int | None
    total_page: int | None


class Index:
    """Serves each group's rows in the given (upstream) order and records every query."""

    def __init__(self, streams: dict[str, list[Row]]) -> None:
        self.streams = streams
        self.queries: list[FilingPageQuery] = []

    async def __call__(self, query, /, *, volatility):
        assert volatility == "high"
        self.queries.append(query)
        records = self.streams[query.group or query.subtype or ""]
        size, number = query.page_size, query.page
        chunk = records[(number - 1) * size : number * size]
        if not chunk:
            return None
        return Page(chunk, len(records), -(-len(records) // size))


async def every_page(index, request, *, page_size):
    """Follow has_more from the first slice and return the filing numbers of each."""
    pages = []
    while True:
        result = await find_filings(request, read_page=index, page_size=page_size)
        pages.append([f.filing_number for f in result.filings])
        if not result.has_more:
            return pages, result
        request = replace(request, offset=request.offset + request.limit)


# Real upstream order on one day: newest first by time, numbers out of order within the day.
# 20261021000442 was filed on 2026-10-22 (rcept_dt), after the date in its number.
MAJOR = (
    "20261022000505",
    "20261022000508",
    "20261022000506",
    "20261022000492",
    "20261022000488",
    "20261021000442",
)
EXCHANGE = (
    "20261022900774",
    "20261022900751",
    "20261022900773",
    "20261022800778",
    "20261022900767",
    "20261022800765",
)


async def test_merged_pages_follow_filing_dates_and_upstream_order():
    major = [row(n, filing_date="20261022") for n in MAJOR] + [
        row(n) for n in ("20261021000431", "20261021000422")
    ]
    exchange = [row(n, "Contract for Sales or Supply") for n in EXCHANGE] + [
        row("20261021900500", "Contract for Sales or Supply")
    ]
    index = Index({"B": major, "I": exchange})
    request = FilingSearchRequest(
        "00164779", WINDOW, categories=("major_issues", "exchange_disclosures"), limit=3
    )
    pages, last = await every_page(index, request, page_size=4)
    flat = [number for page in pages for number in page]
    # One day at a time, newest first; within a day the queries interleave by position.
    expected = [n for pair in zip(MAJOR, EXCHANGE, strict=True) for n in pair]
    assert flat == [*expected, "20261021000431", "20261021900500", "20261021000422"]
    assert len(set(flat)) == len(flat) == 15
    assert last.total == 15
    assert [len(page) for page in pages] == [3, 3, 3, 3, 3]


async def test_title_filters_keep_the_upstream_order():
    # The last page holds a match numbered above matches on earlier pages.
    numbers = (
        *("20261022900774", "20261022800778", "20261022900773", "20261022800765"),
        *("20261022900767", "20261022800729", "20261022900726", "20261022800686"),
        "20261022900751",
    )
    titles = ["Disclosure", "Notice"] * 5
    index = Index({"": [row(n, t) for n, t in zip(numbers, titles, strict=False)]})
    request = FilingSearchRequest(None, WINDOW, title_contains="DISCLOSURE", limit=2)
    pages, last = await every_page(index, request, page_size=4)
    assert pages == [
        ["20261022900774", "20261022900773"],
        ["20261022900767", "20261022900726"],
        ["20261022900751"],
    ]
    assert last.total == 5
    assert last.title_scan is None


async def test_queries_already_further_back_are_not_read_again():
    busy = [row(f"20261022{800100 - n:06d}", "Contract") for n in range(12)]
    days = ["22", "20", "18", "16", "14", "12", "10", "08"]
    quiet = [row(f"202610{day}000100") for day in days]
    index = Index({"I": busy, "B": quiet})
    request = FilingSearchRequest(
        "00164779",
        WINDOW,
        categories=("exchange_disclosures", "major_issues"),
        offset=5,
        limit=5,
    )
    result = await find_filings(request, read_page=index, page_size=4)
    assert [f.filing_number for f in result.filings] == [
        f"20261022{800100 - n:06d}" for n in range(4, 9)
    ]
    assert (result.total, result.has_more) == (20, True)
    assert sorted(query.group for query in index.queries) == ["B", "I", "I", "I"]


async def test_exhausted_merges_count_distinct_filings():
    # A filing arrived between two page reads, so one row repeats on the next page; the
    # undated row (invalid date, no rcept_dt) sorts first.
    shifted = [row(n) for n in ("20261022000003", "20261022000002", "20261022000002")]
    undated = row("20261399000001", filing_date="")
    index = Index({"B": [*shifted, row("20261022000001")], "I": [undated]})
    request = FilingSearchRequest(
        "00164779", WINDOW, categories=("major_issues", "exchange_disclosures")
    )
    result = await find_filings(request, read_page=index, page_size=2)
    assert [f.filing_number for f in result.filings] == [
        "20261399000001",
        "20261022000003",
        "20261022000002",
        "20261022000001",
    ]
    assert result.filings[0].filed is None
    assert (result.total, result.has_more) == (4, False)


async def test_one_category_reads_the_pages_that_cover_the_slice():
    rows = [row(f"20261022{900000 - n:06d}") for n in range(10)]
    index = Index({"B": rows})
    request = FilingSearchRequest(
        "00164779", WINDOW, categories=("major_issues",), final_only=False, offset=3, limit=4
    )
    result = await find_filings(request, read_page=index, page_size=4)
    assert [f.filing_number for f in result.filings] == [r.filing_number for r in rows[3:7]]
    assert (result.total, result.has_more) == (10, True)
    assert [(q.page, q.page_size, q.final_only) for q in index.queries] == [
        (1, 4, False),
        (2, 4, False),
    ]


async def test_rows_are_normalized_and_filters_reach_the_source():
    rows = [
        row("20261022000001", "[Revision of statements]Report on Major Issues", rm="U"),
        row("2026102200000"),
        row("20261021000002", corporation_code=None),
    ]
    index = Index({"I002": rows})
    request = FilingSearchRequest(
        None, WINDOW, categories=("fair_disclosure",), market="KOSDAQ", limit=10
    )
    result = await find_filings(request, read_page=index)
    (filing,) = result.filings
    assert (filing.corp_code, filing.corp_name, filing.market) == ("00164779", "SK hynix", "KOSPI")
    assert (filing.category, filing.is_amendment, filing.corrected_later) == (
        "fair_disclosure",
        True,
        True,
    )
    assert filing.filed == dt.date(2026, 10, 22)
    assert filing.dart_url.endswith("20261022000001")
    (query,) = index.queries
    assert (query.corp_code, query.group, query.subtype, query.corporation_type) == (
        None,
        None,
        "I002",
        "K",
    )
    assert (result.total, result.has_more) == (3, False)


async def test_deep_merged_slices_exceed_the_budget():
    # The categories list the same filings, so each round of three pages adds only 100.
    busy = [row(f"20261022{900000 - n:06d}") for n in range(1000)]
    index = Index({"B": busy, "C": busy, "D": busy})
    request = FilingSearchRequest(
        "00164779",
        WINDOW,
        categories=("major_issues", "offerings", "equity_disclosures"),
        offset=600,
        limit=100,
    )
    with pytest.raises(SearchBudgetError) as raised:
        await find_filings(request, read_page=index, max_calls=20)
    assert (raised.value.offset, raised.value.limit, raised.value.max_calls) == (600, 100, 20)
    assert "need more than 20 page reads" in str(raised.value)
    assert len(index.queries) == 18


async def test_title_scans_report_how_far_back_they_reached():
    rows = [row(f"202610{22 - n // 100:02d}{n:06d}", "Notice") for n in range(1000)]
    index = Index({"": rows})
    messages = []

    async def progress(message):
        messages.append(message)

    request = FilingSearchRequest(None, WINDOW, title_contains="Disclosure")
    result = await find_filings(request, read_page=index, title_scan_calls=3, progress=progress)
    assert result.filings == ()
    assert result.title_scan is not None
    assert (result.title_scan.scanned, result.title_scan.reached) == (300, dt.date(2026, 10, 20))
    assert (result.total, result.has_more) == (None, False)
    assert len(index.queries) == 3
    assert messages[-1] == "Searching filings: 3 result pages read"


def test_requests_outside_what_opendart_serves_are_refused():
    with pytest.raises(ValueError, match="three calendar months"):
        FilingSearchRequest(None, DateWindow(dt.date(2026, 1, 1), dt.date(2026, 10, 22)))
    with pytest.raises(ValueError, match="limit"):
        FilingSearchRequest("00164779", WINDOW, limit=101)
    with pytest.raises(ValueError, match="offset"):
        FilingSearchRequest("00164779", WINDOW, offset=-1)
    with pytest.raises(ValueError, match="page_size"):
        FilingPageQuery("00164779", WINDOW.start, WINDOW.end, page_size=0)
