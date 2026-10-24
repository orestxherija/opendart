"""The find_filings adapter: categories, paging, budgets, and notes through the gateway.

Merge order and paging rules over synthetic pages are tested in the analysis suite.
"""

from __future__ import annotations

import pytest

from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.services.filings import FilingSearch, category_named, find_filings


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
