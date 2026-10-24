"""Read pages of the filing index and merge several category queries newest first.

OpenDART's filing search takes one category code per request and returns at most 100 rows
per page, by filing date (``rcept_dt``) and then time of day, newest first. Filing numbers do
not follow that order within a day (exchange and FSS series interleave), so nothing here
sorts by number. One category is served in upstream order from the pages that cover the
requested slice. Several categories, or a title filter, are read round by round and merged by
filing date, then position in each query; a filing is certain once no unread row can
precede it, so every merged slice is a stable part of one order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from operator import itemgetter
from typing import TYPE_CHECKING, Final

import anyio

from opendart_analysis.domain.filings import clean_title, is_amendment, parse_remarks
from opendart_analysis.domain.identifiers import dart_viewer_url, filing_date, is_filing_number
from opendart_analysis.domain.normalize import clean_text, market_from_corp_cls, parse_date
from opendart_analysis.filings.access import FilingPageQuery
from opendart_analysis.filings.category import category_codes, infer_category

if TYPE_CHECKING:
    from collections.abc import Callable

    from opendart_analysis.domain.categories import FilingCategory
    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.domain.types import Market, MarketFilter
    from opendart_analysis.filings.access import (
        CorporationType,
        ListedFiling,
        Progress,
        ReadFilingPage,
    )

    # Merge position: negated filing-day ordinal, position in the query, query order.
    type _Key = tuple[int, int, int]

_CORPORATION_TYPES: Final[dict[str, CorporationType]] = {
    "KOSPI": "Y",
    "KOSDAQ": "K",
    "KONEX": "N",
    "unlisted": "E",
}
# Day of filings above a query's first dated one: no unread filing can be newer.
_UNDATED: Final = date.max.toordinal()


@dataclass(frozen=True, slots=True)
class Filing:
    """One filing from the index, normalized.

    Attributes:
        filing_number (str): 14-digit filing (receipt) number.
        filed (date | None): Filing date, from the listing or else the filing number.
        corp_code (str): 8-digit DART corporation code of the filer.
        corp_name (str): Company name as listed, or the corp code when blank.
        stock_code (str | None): Stock code of a listed company.
        market (Market | None): Listing market.
        title (str): Report title as filed, whitespace collapsed.
        submitter (str | None): Name of the submitter.
        category (FilingCategory | None): Category searched, or one inferred from the title
            and number when every category was searched.
        is_amendment (bool): Whether the title marks a re-submission of an earlier filing.
        corrected_later (bool): Whether a correction was filed after this filing.
        withdrawn (bool): Whether the filing was withdrawn.
    """

    filing_number: str
    filed: date | None
    corp_code: str
    corp_name: str
    stock_code: str | None
    market: Market | None
    title: str
    submitter: str | None
    category: FilingCategory | None
    is_amendment: bool
    corrected_later: bool
    withdrawn: bool

    @property
    def dart_url(self) -> str:
        """DART viewer link of the filing.

        Returns:
            str: URL for citation.
        """
        return dart_viewer_url(self.filing_number)


def filing_from(row: ListedFiling, category: FilingCategory | None) -> Filing | None:
    """Normalize one search row.

    Args:
        row (ListedFiling): Search row.
        category (FilingCategory | None): Category the row was searched under; None to infer
            one from the title and number.

    Returns:
        Filing | None: The filing, or None for a row without a filing number or company.
    """
    number = (row.filing_number or "").strip()
    corp_code = clean_text(row.corporation_code)
    if not is_filing_number(number) or corp_code is None:
        return None
    title = clean_title(row.report_title or "")
    flags = parse_remarks(row.rm)
    return Filing(
        filing_number=number,
        filed=parse_date(row.filing_date) or filing_date(number),
        corp_code=corp_code,
        corp_name=clean_text(row.corporation_name) or corp_code,
        stock_code=clean_text(row.stock_code),
        market=market_from_corp_cls(row.corporation_type),
        title=title,
        submitter=clean_text(row.submitter_name),
        category=category or infer_category(title, number),
        is_amendment=is_amendment(title),
        corrected_later=flags.corrected_later,
        withdrawn=flags.withdrawn,
    )


@dataclass(frozen=True, slots=True)
class Source:
    """The data source and the upstream parameters shared by every category query.

    Attributes:
        read_page (ReadFilingPage): Reads one upstream page.
        corp_code (str | None): Company to search; None for every company.
        window (DateWindow): Filing dates to cover.
        market (MarketFilter): Listing market filter.
        final_only (bool): Only the latest version of amended filings.
        page_size (int): Rows per upstream page, at most 100.
        progress (Progress): Receives a message after each round of merged pages.
    """

    read_page: ReadFilingPage
    corp_code: str | None
    window: DateWindow
    market: MarketFilter
    final_only: bool
    page_size: int
    progress: Progress


@dataclass(frozen=True, slots=True)
class Outcome:
    """Filings for the requested slice and what is known about the rest.

    Attributes:
        filings (tuple[Filing, ...]): Filings in the slice, newest first.
        total (int | None): Matching filings, when known.
        has_more (bool): Whether filings after the slice may exist.
        complete (bool): False when the call budget ran out before the slice was certain.
        scanned (int): Filings read in merge order, each once.
        reached (date | None): Oldest filing date before which every filing was read; None
            when no filing read is dated.
    """

    filings: tuple[Filing, ...]
    total: int | None
    has_more: bool
    complete: bool = True
    scanned: int = 0
    reached: date | None = None


@dataclass(frozen=True, slots=True)
class _Page:
    """One upstream page of filings."""

    items: tuple[Filing, ...]
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
    items: list[Filing] = field(default_factory=list)
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


async def _page(source: Source, category: FilingCategory | None, number: int) -> _Page:
    """Fetch one upstream page.

    Args:
        source (Source): Data source and shared search parameters.
        category (FilingCategory | None): Category to search, or None for all.
        number (int): 1-based upstream page number.

    Returns:
        _Page: Filings, total matches, and total pages; empty when the source has none.
    """
    group, subtype = category_codes(category)
    query = FilingPageQuery(
        corp_code=source.corp_code,
        start=source.window.start,
        end=source.window.end,
        group=group,
        subtype=subtype,
        final_only=source.final_only,
        corporation_type=_CORPORATION_TYPES.get(source.market),
        page=number,
        page_size=source.page_size,
    )
    response = await source.read_page(query, volatility="high")
    if response is None:
        return _Page((), 0, 0)
    rows = response.list or []
    items = tuple(item for row in rows if (item := filing_from(row, category)) is not None)
    total = len(rows) if response.total_count is None else response.total_count
    pages = (1 if rows else 0) if response.total_page is None else response.total_page
    return _Page(items, total, pages)


def _matcher(text: str | None) -> Callable[[Filing], bool]:
    """Build the title filter.

    Args:
        text (str | None): Required title text; None keeps every filing.

    Returns:
        Callable[[Filing], bool]: Predicate that ignores case and spacing differences.
    """
    needle = " ".join((text or "").split()).casefold()

    def matches(item: Filing) -> bool:
        """Check whether a filing title contains the normalized search text.

        Args:
            item (Filing): Filing to inspect.

        Returns:
            bool: True when its title contains the filter, ignoring case and spacing.
        """
        return needle in item.title.casefold()

    return matches


async def read_single(
    source: Source, category: FilingCategory | None, *, offset: int, limit: int
) -> Outcome:
    """Serve one category without a title filter from the upstream pages that cover a slice.

    Args:
        source (Source): Data source and shared search parameters.
        category (FilingCategory | None): Category, or None for all filings.
        offset (int): Index of the first filing wanted.
        limit (int): Filings wanted, at most the page size.

    Returns:
        Outcome: The filings with the exact total.
    """
    size = source.page_size
    first = offset // size + 1
    page = await _page(source, category, first)
    items = list(page.items)
    last = (offset + limit - 1) // size + 1
    if last > first and page.pages > first:
        items.extend((await _page(source, category, last)).items)
    start = offset - (first - 1) * size
    total = page.total if page.items or first == 1 else None
    has_more = total is not None and offset + limit < total
    return Outcome(tuple(items[start : start + limit]), total, has_more)


@dataclass(slots=True)
class _Merge:
    """Several category queries, or a title filter, read round by round and merged.

    Filings merge by filing date, newest first, then by position in their query, so the
    order does not depend on how many pages were read; within one query it is the upstream
    order. A filing is certain once it precedes every position an unread filing can take.
    """

    source: Source
    streams: list[_Stream]
    matches: Callable[[Filing], bool]

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

    def ordered(self) -> list[Filing]:
        """Merge the filings that no unread filing can precede.

        Returns:
            list[Filing]: Certain filings in merge order, each filing once.
        """
        horizon = self.horizon()
        keyed = (
            (stream.key(index), item)
            for stream in self.streams
            for index, item in enumerate(stream.items)
        )
        kept = sorted((p for p in keyed if horizon is None or p[0] < horizon), key=itemgetter(0))
        unique: dict[str, Filing] = {}
        for _, item in kept:
            unique.setdefault(item.filing_number, item)
        return list(unique.values())

    def certain(self) -> list[Filing]:
        """List the certain filings that match the title filter.

        Returns:
            list[Filing]: Matching filings in merge order.
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
            await self.source.progress(f"Searching filings: {calls} result pages read")
        return True

    async def advance(self, stream: _Stream) -> None:
        """Read the next page of one category query.

        Args:
            stream (_Stream): Query to advance.
        """
        stream.add(await _page(self.source, stream.category, stream.fetched + 1))

    def reached(self) -> date | None:
        """Return the oldest filing date before which every filing has been read.

        Returns:
            date | None: The date, or None when no filing read so far is dated.
        """
        horizon = self.horizon()
        day = _UNDATED if horizon is None else -horizon[0]
        return date.fromordinal(day) if day < _UNDATED else None


async def read_merged(
    source: Source,
    categories: tuple[FilingCategory | None, ...],
    *,
    offset: int,
    limit: int,
    title: str | None,
    budget: int,
) -> Outcome:
    """Merge several category queries, or filter titles, over a bounded number of pages.

    Args:
        source (Source): Data source and shared search parameters.
        categories (tuple[FilingCategory | None, ...]): Disjoint categories.
        offset (int): Index of the first filing wanted.
        limit (int): Filings wanted.
        title (str | None): Text the title must contain; None keeps every filing.
        budget (int): Most upstream calls to make; raised to one per category when lower.

    Returns:
        Outcome: The filings, with ``complete`` False when the budget ran out first. Once
            every query is read the total is the exact count; before that it is OpenDART's
            count without a title filter and unknown with one.
    """
    end = offset + limit
    streams = [_Stream(category, order) for order, category in enumerate(categories)]
    merge = _Merge(source, streams, _matcher(title))
    complete = await merge.scan(wanted=end, budget=max(budget, len(categories)))
    found = merge.certain()
    exhausted = merge.exhausted
    has_more = len(found) > end or (complete and not exhausted)
    if title is None:
        total = len(found) if exhausted else sum(stream.total for stream in merge.streams)
    else:
        total = len(found) if exhausted else None
    return Outcome(
        tuple(found[offset:end]),
        total,
        has_more,
        complete=complete,
        scanned=len(merge.ordered()),
        reached=merge.reached(),
    )
