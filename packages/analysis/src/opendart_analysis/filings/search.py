"""Search the filing index by company or across the market, by category and title.

A request covers one company or every company, a filing-date window (at most three calendar
months without a company, as OpenDART requires), any number of categories, an optional title
filter, and a slice of the results (``offset`` and ``limit``). One category without a title
filter is served from the upstream pages that cover the slice, with OpenDART's exact total.
Several categories, or a title filter, are merged newest first over a bounded number of
upstream calls (see ``opendart_analysis.filings.scan``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.dates import within_three_months
from opendart_analysis.errors import AnalysisError
from opendart_analysis.filings.category import disjoint_categories
from opendart_analysis.filings.scan import Source, read_merged, read_single
from opendart_analysis.upstream import MAX_FILING_PAGE, no_progress

if TYPE_CHECKING:
    from datetime import date

    from opendart_analysis.domain.categories import FilingCategory
    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.domain.types import MarketFilter
    from opendart_analysis.filings.access import ReadFilingPage
    from opendart_analysis.filings.scan import Filing
    from opendart_analysis.upstream import Progress

MAX_CALLS: Final = 20
"""Default for the upstream calls one slice of a multi-category search may take."""
TITLE_SCAN_CALLS: Final = 5
"""Default for the upstream pages read to match title text (500 filings)."""


@dataclass(frozen=True, slots=True)
class FilingSearchRequest:
    """A filing search: who, when, which categories, and which slice of the results.

    Attributes:
        corp_code (str | None): 8-digit DART corporation code; None searches every company.
        window (DateWindow): Filing dates (KST) to cover; at most three calendar months when
            ``corp_code`` is None.
        categories (tuple[FilingCategory, ...]): Categories to include; empty for all.
        market (MarketFilter): Listing market filter.
        title_contains (str | None): Text the title must contain, ignoring case and spacing.
        final_only (bool): Only the latest version of amended filings.
        offset (int): Index of the first filing wanted, newest first.
        limit (int): Filings wanted, 1 to 100.
    """

    corp_code: str | None
    window: DateWindow
    categories: tuple[FilingCategory, ...] = ()
    market: MarketFilter = "all"
    title_contains: str | None = None
    final_only: bool = True
    offset: int = 0
    limit: int = MAX_FILING_PAGE

    def __post_init__(self) -> None:
        """Reject slices and windows OpenDART cannot serve.

        Raises:
            ValueError: ``limit`` is outside 1 to 100, ``offset`` is negative, or a search
                without a company covers more than three calendar months.
        """
        if not 1 <= self.limit <= MAX_FILING_PAGE:
            message = f"limit must be between 1 and {MAX_FILING_PAGE}; got {self.limit}."
            raise ValueError(message)
        if self.offset < 0:
            message = f"offset must not be negative; got {self.offset}."
            raise ValueError(message)
        if self.corp_code is None and not within_three_months(self.window):
            message = "A search without a company can cover at most three calendar months."
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class TitleScan:
    """How far a title filter reached when its page budget ran out.

    Attributes:
        scanned (int): Filings, newest first, whose titles were matched.
        reached (date | None): Oldest filing date reached; None when no filing read is dated.
    """

    scanned: int
    reached: date | None


@dataclass(frozen=True, slots=True)
class FilingResults:
    """One slice of a filing search.

    Attributes:
        filings (tuple[Filing, ...]): Filings in the slice, newest first.
        total (int | None): Matching filings, when known: OpenDART's count for one category,
            the sum of each query's count for several, and the exact count once every page
            has been read; unknown for a title filter that has not read every page.
        has_more (bool): Whether filings after the slice may exist.
        title_scan (TitleScan | None): Set when a title filter stopped at its page budget,
            so older filings in the window were not matched.
    """

    filings: tuple[Filing, ...]
    total: int | None
    has_more: bool
    title_scan: TitleScan | None = None


class SearchBudgetError(AnalysisError):
    """A slice of a multi-category search needs more upstream calls than allowed.

    Attributes:
        offset (int): Index of the first filing requested.
        limit (int): Filings requested.
        max_calls (int): The call budget that ran out.
    """

    def __init__(self, *, offset: int, limit: int, max_calls: int) -> None:
        """Describe the slice that exceeded the budget.

        Args:
            offset (int): Index of the first filing requested.
            limit (int): Filings requested.
            max_calls (int): The call budget that ran out.
        """
        super().__init__(
            f"Filings {offset + 1} to {offset + limit} of this search need more than {max_calls} page reads; narrow the window or request fewer categories."
        )
        self.offset = offset
        self.limit = limit
        self.max_calls = max_calls


async def find_filings(
    request: FilingSearchRequest,
    *,
    read_page: ReadFilingPage,
    max_calls: int = MAX_CALLS,
    title_scan_calls: int = TITLE_SCAN_CALLS,
    page_size: int = MAX_FILING_PAGE,
    progress: Progress = no_progress,
) -> FilingResults:
    """Search the filing index.

    Args:
        request (FilingSearchRequest): What to search and which slice to return.
        read_page (ReadFilingPage): Reads one upstream page, with ``high`` volatility.
        max_calls (int): Most upstream calls one slice of a merged search may take; at least
            one per category is always allowed.
        title_scan_calls (int): Most upstream pages a title filter reads.
        page_size (int): Rows per upstream page, 1 to 100.
        progress (Progress): Receives a message after each round of merged pages.

    Returns:
        FilingResults: The slice newest first, with the total and whether more follow.

    Raises:
        SearchBudgetError: Without a title filter, a merged slice needs more than
            ``max_calls`` upstream calls.
    """
    source = Source(
        read_page,
        request.corp_code,
        request.window,
        request.market,
        request.final_only,
        page_size,
        progress,
    )
    categories = disjoint_categories(request.categories)
    title = request.title_contains
    offset, limit = request.offset, request.limit
    if title is None and len(categories) == 1:
        outcome = await read_single(source, categories[0], offset=offset, limit=limit)
        return FilingResults(outcome.filings, outcome.total, outcome.has_more)
    budget = max_calls if title is None else title_scan_calls
    outcome = await read_merged(
        source,
        categories,
        offset=offset,
        limit=limit,
        title=title,
        budget=budget,
    )
    if outcome.complete:
        return FilingResults(outcome.filings, outcome.total, outcome.has_more)
    if title is None:
        raise SearchBudgetError(offset=offset, limit=limit, max_calls=max_calls)
    scan = TitleScan(outcome.scanned, outcome.reached)
    return FilingResults(outcome.filings, outcome.total, outcome.has_more, scan)
