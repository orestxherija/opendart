"""The filing index: search OpenDART's disclosure list by company or across the market.

Searches resolve the company and the date window, then read the index through
:mod:`opendart_mcp.services.filing_scan`. Without a company, OpenDART limits the window to
three calendar months. Results carry the exact call for the next page, with absolute dates
so that it covers the same window on any day.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.categories import CATEGORY_INFO, FILING_CATEGORIES
from opendart_analysis.domain.dates import cap_to_three_months, resolve_window, within_three_months
from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.progress import no_progress
from opendart_mcp.models.common import NextCall, Pagination
from opendart_mcp.models.filings import SearchFilingsResult
from opendart_mcp.services.filing_scan import UPSTREAM_PAGE, Query, read_merged, read_single

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic import JsonValue

    from opendart_analysis.domain.categories import FilingCategory
    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.domain.types import MarketFilter
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company

DEFAULT_SINCE: Final = "90d"
DEFAULT_LIMIT: Final = 50
WINDOW_TOO_WIDE: Final = "OpenDART limits searches without a company to three months; narrow since/until or pass company."


@dataclass(frozen=True, slots=True)
class FilingSearch:
    """A filing search as tools and resources request it.

    Attributes:
        company (str | None): Company name or code; None searches every company.
        categories (tuple[FilingCategory, ...]): Categories to include; empty for all.
        since (str): Window start: ISO date, or a duration counted back from ``until``.
        until (str | None): Window end; None for today (KST).
        market (MarketFilter): Listing market filter.
        title_contains (str | None): Text the title must contain, ignoring case.
        final_only (bool): Only the latest version of amended filings.
        limit (int): Filings per page, at most 100.
        page (int): 1-based page.
    """

    company: str | None = None
    categories: tuple[FilingCategory, ...] = ()
    since: str = DEFAULT_SINCE
    until: str | None = None
    market: MarketFilter = "all"
    title_contains: str | None = None
    final_only: bool = True
    limit: int = DEFAULT_LIMIT
    page: int = 1

    @property
    def offset(self) -> int:
        """Index of the first filing on the requested page.

        Returns:
            int: Zero-based offset.
        """
        return (self.page - 1) * self.limit


def _window(
    state: AppState, search: FilingSearch, *, market_wide: bool
) -> tuple[DateWindow, list[str]]:
    """Resolve the date window, keeping market-wide searches within three months.

    The default window counts 90 days, which exceeds three calendar months on a few dates;
    it is shortened with a note. Explicit windows that are too wide are refused.

    Args:
        state (AppState): Server state.
        search (FilingSearch): Requested search.
        market_wide (bool): Whether no company was given.

    Returns:
        tuple[DateWindow, list[str]]: Window and notes.

    Raises:
        InvalidArgumentError: A date is invalid, or an explicit market-wide window is too wide.
    """
    try:
        window = resolve_window(
            search.since, search.until, today=state.today(), default_since=DEFAULT_SINCE
        )
    except ValueError as error:
        message = str(error)
        raise InvalidArgumentError(message) from error
    if not market_wide or within_three_months(window):
        return window, []
    if search.since != DEFAULT_SINCE:
        raise InvalidArgumentError(WINDOW_TOO_WIDE)
    capped = cap_to_three_months(window)
    note = f"The window starts on {capped.start.isoformat()}: OpenDART limits searches without a company to three calendar months."
    return capped, [note]


def disjoint_categories(
    categories: Sequence[FilingCategory],
) -> tuple[FilingCategory | None, ...]:
    """Drop repeated categories and subtypes whose group is also requested.

    Args:
        categories (Sequence[FilingCategory]): Requested categories; empty for all.

    Returns:
        tuple[FilingCategory | None, ...]: Disjoint categories, or ``(None,)`` for all filings.
    """
    if not categories:
        return (None,)
    unique = list(dict.fromkeys(categories))
    groups = {CATEGORY_INFO[c].group for c in unique if CATEGORY_INFO[c].subtype is None}
    return tuple(
        c
        for c in unique
        if CATEGORY_INFO[c].subtype is None or CATEGORY_INFO[c].group not in groups
    )


def _arguments(
    search: FilingSearch, company: Company | None, window: DateWindow
) -> dict[str, JsonValue]:
    """Build the arguments of the call for the next page.

    Args:
        search (FilingSearch): Requested search.
        company (Company | None): Resolved company.
        window (DateWindow): Window searched.

    Returns:
        dict[str, JsonValue]: Arguments for search_filings, with absolute dates.
    """
    optional: dict[str, JsonValue] = {
        "company": company.corp_code if company else None,
        "categories": [str(category) for category in search.categories] or None,
        "market": None if search.market == "all" else search.market,
        "title_contains": search.title_contains,
        "final_only": None if search.final_only else False,
    }
    arguments: dict[str, JsonValue] = {k: v for k, v in optional.items() if v is not None}
    arguments.update(
        since=window.start.isoformat(),
        until=window.end.isoformat(),
        limit=search.limit,
        page=search.page + 1,
    )
    return arguments


def _empty_note(search: FilingSearch, window: DateWindow) -> str:
    """Explain an empty page.

    Args:
        search (FilingSearch): Requested search.
        window (DateWindow): Window searched.

    Returns:
        str: Note with what to change.
    """
    if search.page > 1:
        return f"Page {search.page} is past the end of the results; request an earlier page."
    scope = "this company" if search.company else "any company"
    return f"No filings by {scope} matched from {window.start.isoformat()} to {window.end.isoformat()}. Widen since/until, drop categories or title_contains, or set final_only=false."


async def find_filings(
    state: AppState, search: FilingSearch, *, progress: Progress = no_progress
) -> SearchFilingsResult:
    """Search the filing index.

    Args:
        state (AppState): Server state.
        search (FilingSearch): What to search.
        progress (Progress): Reports directory loading and multi-page reads.

    Returns:
        SearchFilingsResult: Filings newest first, with paging and the exact next call.

    Raises:
        InvalidArgumentError: Invalid dates, a market-wide window wider than three months, or
            a page that needs too many upstream requests.
    """
    company = (
        await state.companies.resolve(search.company, progress=progress) if search.company else None
    )
    window, notes = _window(state, search, market_wide=company is None)
    query = Query(
        state, company.corp_code if company else None, window, search.market, search.final_only
    )
    categories = disjoint_categories(search.categories)
    if search.title_contains is None and len(categories) == 1:
        outcome = await read_single(query, categories[0], offset=search.offset, limit=search.limit)
    else:
        outcome = await read_merged(
            query,
            categories,
            offset=search.offset,
            limit=search.limit,
            title=search.title_contains,
            progress=progress,
        )
    notes.extend(outcome.notes)
    if not outcome.items:
        notes.append(_empty_note(search, window))
    # Every filing of a company search names the same company, given once at the top.
    items = (
        [item.model_copy(update={"company": None}) for item in outcome.items]
        if company
        else outcome.items
    )
    next_call = (
        NextCall(tool="search_filings", arguments=_arguments(search, company, window))
        if outcome.has_more
        else None
    )
    pagination = Pagination(
        total=outcome.total,
        page=search.page,
        limit=search.limit,
        has_more=outcome.has_more,
        next_call=next_call,
    )
    return SearchFilingsResult(
        company=company.ref if company else None,
        since=window.start,
        until=window.end,
        filings=items,
        pagination=pagination,
        notes=notes,
        as_of=state.today(),
    )


def category_named(text: str) -> FilingCategory:
    """Validate a category name given as free text, such as a resource query parameter.

    Args:
        text (str): Category name.

    Returns:
        FilingCategory: The category.

    Raises:
        InvalidArgumentError: The name is not a filing category.
    """
    name = text.strip()
    for category in FILING_CATEGORIES:
        if category == name:
            return category
    message = f"Unknown filing category {text!r}; use one of: {", ".join(FILING_CATEGORIES)}."
    raise InvalidArgumentError(message)


async def company_filing_index(
    state: AppState, corp_code: str, *, since: str = DEFAULT_SINCE, category: str | None = None
) -> SearchFilingsResult:
    """List one company's filings for the filing-index resource.

    Args:
        state (AppState): Server state.
        corp_code (str): DART corporation code (names and stock codes also resolve).
        since (str): Window start; defaults to the last 90 days.
        category (str | None): Category name; None for all filings.

    Returns:
        SearchFilingsResult: Up to 100 filings, newest first.
    """
    categories = () if category is None else (category_named(category),)
    search = FilingSearch(
        company=corp_code, categories=categories, since=since, limit=UPSTREAM_PAGE
    )
    return await find_filings(state, search)
