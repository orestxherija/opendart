"""Read pages of the filing index and merge several category queries newest first.

``disclosures.search`` takes one category code per request and returns at most 100 rows per
page, by filing date (``rcept_dt``) and then time of day, newest first. Filing numbers do
not follow that order within a day (exchange and FSS series interleave), so nothing here
sorts by number. One category is served in upstream order from the pages that cover the
requested page. Several categories, or a title filter, are read round by round and merged by
filing date, then position in each query; a filing is certain once no unread row can
precede it, so every merged page is a stable slice of one order.

Upstream quirk, verified live: ``pblntf_detail_ty`` filters only when ``pblntf_ty`` is
omitted. Sent together, the subtype is ignored and the whole group comes back, so subtype
categories send the subtype alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Final, Literal

import anyio

from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.ttl import FILINGS
from opendart_mcp.domain.categories import category_query
from opendart_mcp.domain.dates import yyyymmdd
from opendart_mcp.domain.filings import clean_title, is_amendment, parse_remarks
from opendart_mcp.domain.identifiers import (
    dart_viewer_url,
    filing_date,
    is_filing_number,
)
from opendart_mcp.domain.normalize import clean_text, market_from_corp_cls, parse_date
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.models.filings import FilingItem
from opendart_mcp.services.filing_category import infer_category

if TYPE_CHECKING:
    from collections.abc import Callable

    from opendart.models.disclosures import ListResponseListItem
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.categories import FilingCategory
    from opendart_mcp.domain.dates import DateWindow
    from opendart_mcp.domain.types import MarketFilter

    # Merge position: negated filing-day ordinal, position in the query, query order.
    type _Key = tuple[int, int, int]

UPSTREAM_PAGE: Final = 100
"""Rows per upstream page, OpenDART's maximum."""
MAX_CALLS: Final = 20
"""Upstream calls one page of a multi-category search may take."""
TITLE_SCAN_CALLS: Final = 5
"""Upstream pages read to match title text (500 filings)."""

_CORPORATION_TYPES: Final[dict[str, Literal["Y", "K", "N", "E"]]] = {
    "KOSPI": "Y",
    "KOSDAQ": "K",
    "KONEX": "N",
    "unlisted": "E",
}
# Day of filings above a query's first dated one: no unread filing can be newer.
_UNDATED: Final = date.max.toordinal()


@dataclass(frozen=True, slots=True)
class Query:
    """Server state and the upstream parameters shared by every category query.

    Attributes:
        state (AppState): Server state.
        corp_code (str | None): Company to search; None for every company.
        window (DateWindow): Filing dates to cover.
        market (MarketFilter): Listing market filter.
        final_only (bool): Only the latest version of amended filings.
    """

    state: AppState
    corp_code: str | None
    window: DateWindow
    market: MarketFilter
    final_only: bool


@dataclass(frozen=True, slots=True)
class Outcome:
    """Filings for the requested page and what is known about the rest.

    Attributes:
        items (list[FilingItem]): Filings on the page, newest first.
        total (int | None): Matching filings, when known.
        has_more (bool): Whether another page may hold more.
        notes (list[str]): Coverage caveats.
    """

    items: list[FilingItem]
    total: int | None
    has_more: bool
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Page:
    """One upstream page of filings."""

    items: tuple[FilingItem, ...]
    total: int
    pages: int


@dataclass(slots=True)
class _Stream:
    """The pages read so far for one category query, in upstream order.

    ``days`` holds each filing's date ordinal as a running minimum, so it never increases
    along the query, even past a row listed out of date order.
    """

    category: FilingCategory | None
    order: int
    items: list[FilingItem] = field(default_factory=list)
    days: list[int] = field(default_factory=list)
    total: int = 0
    fetched: int = 0
    pages: int | None = None

    @property
    def exhausted(self) -> bool:
        """Whether every page of the query has been read.

        Returns:
            bool: True after the last page.
        """
        return self.pages is not None and self.fetched >= self.pages

    def add(self, page: _Page) -> None:
        """Append the next page.

        Args:
            page (_Page): Page number ``fetched + 1``.
        """
        day = self.days[-1] if self.days else _UNDATED
        for item in page.items:
            day = min(day, item.filed.toordinal()) if item.filed else day
            self.days.append(day)
        self.items.extend(page.items)
        self.total, self.pages = page.total, page.pages
        self.fetched += 1

    def key(self, index: int) -> _Key:
        """Return the merge position of a filing read: newest date first, then upstream order.

        Args:
            index (int): Position of the filing in the query.

        Returns:
            _Key: Sort key, unique across queries.
        """
        return (-self.days[index], index, self.order)

    def bound(self) -> _Key:
        """Return the earliest merge position an unread filing of the query can take.

        Returns:
            _Key: Unread filings are dated no later than the last one read and follow it.
        """
        return (-(self.days[-1] if self.days else _UNDATED), len(self.items), self.order)


def category_codes(category: FilingCategory | None) -> tuple[Any, Any]:
    """Return ``pblntf_ty`` and ``pblntf_detail_ty`` for a category.

    Subtypes are sent without their group, because OpenDART ignores a subtype sent with one.

    Args:
        category (FilingCategory | None): Category, or None for every filing.

    Returns:
        tuple[Any, Any]: Group and subtype codes, either possibly None.
    """
    if category is None:
        return None, None
    group, subtype = category_query(category)
    return (None, subtype) if subtype else (group, None)


def _item(row: ListResponseListItem, category: FilingCategory | None) -> FilingItem | None:
    """Normalize one search row.

    Args:
        row (ListResponseListItem): Upstream row.
        category (FilingCategory | None): Category the row was searched under.

    Returns:
        FilingItem | None: The filing, or None for a row without a filing number or company.
    """
    number = (row.filing_number or "").strip()
    corp_code = clean_text(row.corporation_code)
    if not is_filing_number(number) or corp_code is None:
        return None
    title = clean_title(row.report_title or "")
    flags = parse_remarks(row.rm)
    company = CompanyRef(
        name=clean_text(row.corporation_name) or corp_code,
        corp_code=corp_code,
        stock_code=clean_text(row.stock_code),
        market=market_from_corp_cls(row.corporation_type),
    )
    return FilingItem(
        filing_number=number,
        filed=parse_date(row.filing_date) or filing_date(number),
        company=company,
        title=title,
        submitter=clean_text(row.submitter_name),
        category=category or infer_category(title, number),
        is_amendment=is_amendment(title),
        corrected_later=flags.corrected_later or None,
        withdrawn=flags.withdrawn or None,
        dart_url=dart_viewer_url(number),
    )


async def _page(query: Query, category: FilingCategory | None, number: int) -> _Page:
    """Fetch one upstream page.

    Args:
        query (Query): Shared search parameters.
        category (FilingCategory | None): Category to search, or None for all.
        number (int): 1-based upstream page number.

    Returns:
        _Page: Filings, total matches, and total pages; empty when OpenDART has none.
    """
    gateway = query.state.require_gateway()
    group, subtype = category_codes(category)
    response = await gateway.call(
        FILINGS,
        gateway.sdk.disclosures.search,
        corporation_code=query.corp_code,
        filing_start_date=yyyymmdd(query.window.start),
        filing_end_date=yyyymmdd(query.window.end),
        final_reports_only="Y" if query.final_only else None,
        disclosure_category=group,
        disclosure_subcategory=subtype,
        corporation_type=_CORPORATION_TYPES.get(query.market),
        page_number=number,
        page_size=UPSTREAM_PAGE,
    )
    if response is None:
        return _Page((), 0, 0)
    rows = response.list or []
    items = tuple(item for row in rows if (item := _item(row, category)) is not None)
    total = len(rows) if response.total_count is None else response.total_count
    pages = (1 if rows else 0) if response.total_page is None else response.total_page
    return _Page(items, total, pages)


def _matcher(text: str | None) -> Callable[[FilingItem], bool]:
    """Build the title filter.

    Args:
        text (str | None): Required title text; None keeps every filing.

    Returns:
        Callable[[FilingItem], bool]: Predicate that ignores case and spacing differences.
    """
    needle = " ".join((text or "").split()).casefold()

    def matches(item: FilingItem) -> bool:
        """Check whether a filing title contains the normalized search text.

        Args:
            item (FilingItem): Filing to inspect.

        Returns:
            bool: True when its title contains the filter, ignoring case and spacing.
        """
        return needle in item.title.casefold()

    return matches


async def read_single(
    query: Query, category: FilingCategory | None, *, offset: int, limit: int
) -> Outcome:
    """Serve one category without a title filter from the upstream pages that cover a page.

    Args:
        query (Query): Shared search parameters.
        category (FilingCategory | None): Category, or None for all filings.
        offset (int): Index of the first filing wanted.
        limit (int): Filings wanted, at most 100.

    Returns:
        Outcome: The filings with the exact total.
    """
    first = offset // UPSTREAM_PAGE + 1
    page = await _page(query, category, first)
    items = list(page.items)
    last = (offset + limit - 1) // UPSTREAM_PAGE + 1
    if last > first and page.pages > first:
        items.extend((await _page(query, category, last)).items)
    start = offset - (first - 1) * UPSTREAM_PAGE
    total = page.total if page.items or first == 1 else None
    has_more = total is not None and offset + limit < total
    return Outcome(items[start : start + limit], total, has_more)


@dataclass(slots=True)
class _Merge:
    """Several category queries, or a title filter, read round by round and merged.

    Filings merge by filing date, newest first, then by position in their query, so the
    order does not depend on how many pages were read; within one query it is the upstream
    order. A filing is certain once it precedes every position an unread filing can take.
    """

    query: Query
    streams: list[_Stream]
    matches: Callable[[FilingItem], bool]
    progress: Progress

    @property
    def exhausted(self) -> bool:
        """Whether every query has been read to its end.

        Returns:
            bool: True when no page is left.
        """
        return all(stream.exhausted for stream in self.streams)

    def horizon(self) -> _Key | None:
        """Return the earliest merge position an unread filing can take.

        Returns:
            _Key | None: Filings before it are certain; None when everything is read.
        """
        return min((s.bound() for s in self.streams if not s.exhausted), default=None)

    def ordered(self) -> list[FilingItem]:
        """Merge the filings that no unread filing can precede.

        Returns:
            list[FilingItem]: Certain filings in merge order, each filing once.
        """
        horizon = self.horizon()
        keyed = (
            (stream.key(index), item)
            for stream in self.streams
            for index, item in enumerate(stream.items)
        )
        kept = sorted((p for p in keyed if horizon is None or p[0] < horizon), key=itemgetter(0))
        unique: dict[str, FilingItem] = {}
        for _, item in kept:
            unique.setdefault(item.filing_number, item)
        return list(unique.values())

    def certain(self) -> list[FilingItem]:
        """List the certain filings that match the title filter.

        Returns:
            list[FilingItem]: Matching filings in merge order.
        """
        return [item for item in self.ordered() if self.matches(item)]

    def blocking(self) -> list[_Stream]:
        """Return the unfinished queries that have not read past the newest unread date.

        Queries already further back cannot move the horizon, so they are not read.

        Returns:
            list[_Stream]: Queries to read next; empty when everything is read.
        """
        horizon = self.horizon()
        if horizon is None:
            return []
        return [s for s in self.streams if not s.exhausted and s.bound()[0] == horizon[0]]

    async def scan(self, *, wanted: int, budget: int) -> bool:
        """Read pages round by round until ``wanted`` matching filings are certain.

        Args:
            wanted (int): Matching filings needed.
            budget (int): Most upstream calls to make.

        Returns:
            bool: False when the budget ran out first.
        """
        calls = 0
        while len(self.certain()) < wanted:
            pending = self.blocking()
            if not pending:
                break
            if calls + len(pending) > budget:
                return False
            async with anyio.create_task_group() as group:
                for stream in pending:
                    group.start_soon(self.advance, stream)
            calls += len(pending)
            await self.progress(f"Searching filings: {calls} result pages read")
        return True

    async def advance(self, stream: _Stream) -> None:
        """Read the next page of one category query.

        Args:
            stream (_Stream): Query to advance.
        """
        stream.add(await _page(self.query, stream.category, stream.fetched + 1))

    def coverage_note(self) -> str:
        """Explain how far back an incomplete title filter reached.

        Returns:
            str: Note naming the number of filings matched and the oldest date reached.
        """
        horizon = self.horizon()
        day = _UNDATED if horizon is None else -horizon[0]
        back = f" back to {date.fromordinal(day).isoformat()}" if day < _UNDATED else ""
        return f"title_contains was matched against the newest {len(self.ordered())} filings{back}; older filings in the window were not read. Narrow since/until or categories to search further back."


async def read_merged(
    query: Query,
    categories: tuple[FilingCategory | None, ...],
    *,
    offset: int,
    limit: int,
    title: str | None,
    progress: Progress,
) -> Outcome:
    """Merge several category queries, or filter titles, over a bounded number of pages.

    Args:
        query (Query): Shared search parameters.
        categories (tuple[FilingCategory | None, ...]): Disjoint categories.
        offset (int): Index of the first filing wanted.
        limit (int): Filings wanted.
        title (str | None): Text the title must contain; None keeps every filing.
        progress (Progress): Receives a message after each round of pages.

    Returns:
        Outcome: The filings. Once every query is read the total is the exact count; before
            that it is OpenDART's count without a title filter and unknown with one.

    Raises:
        InvalidArgumentError: The page lies beyond what the call budget can merge.
    """
    end = offset + limit
    streams = [_Stream(category, order) for order, category in enumerate(categories)]
    merge = _Merge(query, streams, _matcher(title), progress)
    budget = max(MAX_CALLS if title is None else TITLE_SCAN_CALLS, len(categories))
    complete = await merge.scan(wanted=end, budget=budget)
    found = merge.certain()
    exhausted = merge.exhausted
    has_more = len(found) > end or (complete and not exhausted)
    if title is None:
        if not complete:
            message = f"Page {offset // limit + 1} of this search needs more than {MAX_CALLS} OpenDART requests; narrow since/until or pass fewer categories."
            raise InvalidArgumentError(message)
        total = len(found) if exhausted else sum(stream.total for stream in merge.streams)
        return Outcome(found[offset:end], total, has_more)
    notes = [] if complete else [merge.coverage_note()]
    return Outcome(found[offset:end], len(found) if exhausted else None, has_more, notes)
