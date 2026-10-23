"""find_filings internals: category codes, merging category queries, paging limits."""

from __future__ import annotations

from dataclasses import replace

import pytest

from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.services import filing_scan
from opendart_mcp.services.filing_category import infer_category
from opendart_mcp.services.filing_scan import category_codes
from opendart_mcp.services.filings import (
    FilingSearch,
    category_named,
    disjoint_categories,
    find_filings,
)


def row(number, title="Report on Major Issues", **fields):
    return {
        "corp_cls": "Y",
        "corp_name": "SK hynix",
        "corp_code": "00164779",
        "stock_code": "000660",
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": "SK하이닉스",
        "rcept_dt": number[:8],
        "rm": "",
        **fields,
    }


@pytest.fixture
async def state(mcp_settings, sdk_settings, upstream, now):
    upstream.route("/corpCode.xml", upstream.corp_archive())
    async with open_state(
        mcp_settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as opened:
        yield opened


def test_subtypes_covered_by_a_requested_group_are_dropped():
    assert disjoint_categories(()) == (None,)
    assert disjoint_categories(
        ("fair_disclosure", "exchange_disclosures", "annual_report", "annual_report")
    ) == ("exchange_disclosures", "annual_report")


def test_subtypes_are_sent_without_their_group():
    assert category_codes(None) == (None, None)
    assert category_codes("major_issues") == ("B", None)
    assert category_codes("fair_disclosure") == (None, "I002")


@pytest.mark.parametrize(
    ("title", "number", "category"),
    [
        ("Quarterly Report (2026.03)", "20260515002181", "quarterly_report"),
        ("Organization of Investor Relations Event", "20261008800028", "exchange_disclosures"),
        ("Contract for Sales or Supply", "20261022900740", "exchange_disclosures"),
        (
            "Report on significant holdings of stocks, etc. (General)",
            "20261016000505",
            "major_holding_report",
        ),
        (
            "Report on status of specific securities, etc. owned by executives and major shareholders",
            "20261019000318",
            "insider_ownership_report",
        ),
        (
            "Report on trading plan of specific securities, etc. by executive officers and major shareholders",
            "20261013000379",
            "insider_trading_plan",
        ),
        ("[Revision of statements]Audit Report (2025.12)", "20260320000111", "audit_reports"),
        ("Treasury Stock Acquisition Result Report", "20261012000421", None),
    ],
)
def test_categories_are_inferred_from_titles_and_numbers(title, number, category):
    assert infer_category(title, number) == category


def test_category_names_are_validated():
    assert category_named(" tender_offer ") == "tender_offer"
    with pytest.raises(InvalidArgumentError, match="Unknown filing category 'rumor'"):
        category_named("rumor")


@pytest.mark.anyio
async def test_merges_keep_only_filings_no_unread_page_can_precede(state, upstream):
    def by_category(request):
        page = int(request.url.params.get("page_no", "1"))
        if request.url.params.get("pblntf_ty") == "B":
            numbers = [f"202610{20 - page:02d}{n:06d}" for n in range(100, 0, -1)]
            return upstream.rows(*map(row, numbers), total_count=150, total_page=2)
        return upstream.rows(
            row("20261021900002", "Contract for Sales or Supply"),
            row("20261015900001", "Contract for Sales or Supply"),
            total_count=2,
            total_page=1,
        )

    upstream.route("/list.json", by_category)
    search = FilingSearch(categories=("major_issues", "ad_hoc_disclosure"), since="1m", limit=10)
    result = await find_filings(state, search)
    numbers = [f.filing_number for f in result.filings]
    assert numbers[0] == "20261021900002"
    assert numbers[1:] == [f"20261019{n:06d}" for n in range(100, 91, -1)]
    assert result.pagination.total == 152
    assert result.pagination.has_more is True
    assert upstream.count("/list.json") == 2


@pytest.mark.anyio
async def test_deep_merged_pages_are_refused(state, upstream):
    def busy(request):
        page = int(request.url.params["page_no"])
        numbers = [f"20261022{900000 - page * 1000 - n:06d}" for n in range(100)]
        return upstream.rows(*map(row, numbers), total_count=5000, total_page=50)

    upstream.route("/list.json", busy)
    search = FilingSearch(
        categories=("major_issues", "offerings", "equity_disclosures"),
        since="1d",
        limit=100,
        page=7,
    )
    with pytest.raises(InvalidArgumentError, match="Page 7 of this search needs more than 20"):
        await find_filings(state, search)


@pytest.mark.anyio
async def test_rows_without_numbers_and_missing_counters_are_tolerated(state, upstream):
    upstream.records(
        "/list.json",
        row("20261022000001"),
        row("2026102200000"),
        row("20261021000002", corp_code=None),
    )
    result = await find_filings(state, FilingSearch(since="1d"))
    assert [f.filing_number for f in result.filings] == ["20261022000001"]
    assert result.pagination.total == 3
    assert result.pagination.has_more is False


@pytest.mark.anyio
async def test_pages_past_the_end_are_explained(state, upstream):
    result = await find_filings(state, FilingSearch(since="1d", limit=100, page=3))
    assert result.filings == []
    assert result.pagination.total is None
    assert result.notes == ["Page 3 is past the end of the results; request an earlier page."]
    assert upstream.params("/list.json")[0]["page_no"] == "3"


@pytest.mark.anyio
async def test_title_filters_stop_once_the_page_is_full(state, upstream):
    def pages(request):
        page = int(request.url.params["page_no"])
        numbers = [f"20261022{900000 - page * 100 - n:06d}" for n in range(100)]
        return upstream.rows(
            *(row(n, "Notice on Investor Relations") for n in numbers),
            total_count=300,
            total_page=3,
        )

    upstream.route("/list.json", pages)
    search = FilingSearch(since="1d", title_contains="investor relations", limit=20)
    result = await find_filings(state, search)
    assert len(result.filings) == 20
    assert result.pagination.total is None
    assert result.pagination.has_more is True
    assert result.notes == []
    assert upstream.count("/list.json") == 1


def serve_pages(upstream, streams):
    """Serve each group's rows in the given (upstream) order, honoring page_no and page_count."""

    def pages(request):
        params = request.url.params
        records = streams[params.get("pblntf_ty", "")]
        size, number = int(params["page_count"]), int(params["page_no"])
        chunk = records[(number - 1) * size : number * size]
        if not chunk:
            return upstream.status("013")
        count = len(records)
        return upstream.rows(*chunk, total_count=count, total_page=-(-count // size))

    upstream.route("/list.json", pages)


async def every_page(state, search):
    """Follow has_more from page 1 and return the filing numbers of each page."""
    pages, page = [], 1
    while True:
        result = await find_filings(state, search)
        pages.append([f.filing_number for f in result.filings])
        if not result.pagination.has_more:
            return pages, result
        page += 1
        search = replace(search, page=page)


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


@pytest.mark.anyio
async def test_merged_pages_follow_filing_dates_and_upstream_order(state, upstream, monkeypatch):
    monkeypatch.setattr(filing_scan, "UPSTREAM_PAGE", 4)
    major = [row(n, rcept_dt="20261022") for n in MAJOR] + [
        row(n) for n in ("20261021000431", "20261021000422")
    ]
    exchange = [row(n, "Contract for Sales or Supply") for n in EXCHANGE] + [
        row("20261021900500", "Contract for Sales or Supply")
    ]
    serve_pages(upstream, {"B": major, "I": exchange})
    search = FilingSearch(categories=("major_issues", "exchange_disclosures"), since="2d", limit=3)
    pages, last = await every_page(state, search)
    flat = [number for page in pages for number in page]
    # One day at a time, newest first; within a day the queries interleave by position.
    expected = [n for pair in zip(MAJOR, EXCHANGE, strict=True) for n in pair]
    assert flat == [*expected, "20261021000431", "20261021900500", "20261021000422"]
    assert len(set(flat)) == len(flat) == 15
    assert last.pagination.total == 15
    assert [len(page) for page in pages] == [3, 3, 3, 3, 3]


@pytest.mark.anyio
async def test_title_filters_keep_the_upstream_order(state, upstream, monkeypatch):
    monkeypatch.setattr(filing_scan, "UPSTREAM_PAGE", 4)
    # The last page holds a match numbered above matches on earlier pages.
    numbers = (
        *("20261022900774", "20261022800778", "20261022900773", "20261022800765"),
        *("20261022900767", "20261022800729", "20261022900726", "20261022800686"),
        "20261022900751",
    )
    titles = ["Disclosure", "Notice"] * 5
    serve_pages(upstream, {"": [row(n, t) for n, t in zip(numbers, titles, strict=False)]})
    search = FilingSearch(since="1d", title_contains="DISCLOSURE", limit=2)
    pages, last = await every_page(state, search)
    assert pages == [
        ["20261022900774", "20261022900773"],
        ["20261022900767", "20261022900726"],
        ["20261022900751"],
    ]
    assert last.pagination.total == 5


@pytest.mark.anyio
async def test_queries_already_further_back_are_not_read_again(state, upstream, monkeypatch):
    monkeypatch.setattr(filing_scan, "UPSTREAM_PAGE", 4)
    busy = [row(f"20261022{800100 - n:06d}", "Contract") for n in range(12)]
    days = ["22", "20", "18", "16", "14", "12", "10", "08"]
    quiet = [row(f"202610{day}000100") for day in days]
    serve_pages(upstream, {"I": busy, "B": quiet})
    search = FilingSearch(
        categories=("exchange_disclosures", "major_issues"), since="1m", limit=5, page=2
    )
    result = await find_filings(state, search)
    assert [f.filing_number for f in result.filings] == [
        f"20261022{800100 - n:06d}" for n in range(4, 9)
    ]
    assert (result.pagination.total, result.pagination.has_more) == (20, True)
    groups = [query["pblntf_ty"] for query in upstream.params("/list.json")]
    assert sorted(groups) == ["B", "I", "I", "I"]


@pytest.mark.anyio
async def test_exhausted_merges_count_distinct_filings(state, upstream, monkeypatch):
    monkeypatch.setattr(filing_scan, "UPSTREAM_PAGE", 2)
    # A filing arrived between two page reads, so one row repeats on the next page; the
    # undated row (invalid date, no rcept_dt) sorts first.
    shifted = [row(n) for n in ("20261022000003", "20261022000002", "20261022000002")]
    undated = row("20261399000001", rcept_dt="")
    serve_pages(upstream, {"B": [*shifted, row("20261022000001")], "I": [undated]})
    result = await find_filings(
        state, FilingSearch(categories=("major_issues", "exchange_disclosures"), since="1d")
    )
    assert [f.filing_number for f in result.filings] == [
        "20261399000001",
        "20261022000003",
        "20261022000002",
        "20261022000001",
    ]
    assert result.filings[0].filed is None
    assert (result.pagination.total, result.pagination.has_more) == (4, False)


@pytest.mark.anyio
async def test_title_notes_omit_the_date_when_no_filing_is_dated(state, upstream):
    def undated(request):
        page = int(request.url.params["page_no"])
        records = [row(f"20261399{page:03d}{n:03d}", "Notice", rcept_dt="") for n in range(100)]
        return upstream.rows(*records, total_count=1000, total_page=10)

    upstream.route("/list.json", undated)
    result = await find_filings(state, FilingSearch(since="1d", title_contains="Disclosure"))
    assert result.filings == []
    assert result.notes[0].startswith("title_contains was matched against the newest 500 filings;")
