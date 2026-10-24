"""The company's filing index, used to decide which event services to call.

Searching the company's major-issue (B) and offering (C) filings costs one or two calls and
names the reports actually filed, so get_corporate_events reads only those services instead
of all 42. The search lists amendments too ([Corrected description] and similar markers),
which tells the events service which rows reflect a corrected filing. Major-issue filings
whose titles no structured service covers are reported so the model can read them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.catalog import EVENT_KINDS
from opendart_analysis.domain.dates import yyyymmdd
from opendart_analysis.domain.filings import clean_title
from opendart_mcp.core.ttl import FILINGS
from opendart_mcp.events.titles import kind_for_title

if TYPE_CHECKING:
    from opendart.models.disclosures import ListResponse
    from opendart_analysis.catalog import EventKind
    from opendart_analysis.domain.dates import DateWindow
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company

type IndexGroup = Literal["B", "C"]

INDEX_GROUPS: Final[tuple[IndexGroup, ...]] = ("B", "C")
"""Disclosure groups searched: major issues and offerings (domain EVENT_INDEX_CATEGORIES)."""
GROUP_RESOURCES: Final[dict[IndexGroup, str]] = {
    "B": "major_issues",
    "C": "securities_registration",
}
"""SDK resource whose services report the filings of each group."""
PAGE_SIZE: Final = 100
MAX_PAGES: Final = 3
"""Pages read per group; beyond them every kind of the group is read instead."""


@dataclass(frozen=True, slots=True)
class IndexedFiling:
    """One filing from the index.

    Attributes:
        filing_number (str): Filing number.
        title (str): Title as listed, whitespace collapsed.
        group (IndexGroup): Disclosure group, B (major issues) or C (offerings).
    """

    filing_number: str
    title: str
    group: IndexGroup

    @property
    def kind(self) -> EventKind | None:
        """Event kind whose service reports this filing.

        Returns:
            EventKind | None: The kind, or None when no structured service covers it.
        """
        return kind_for_title(self.title)


@dataclass(frozen=True, slots=True)
class EventIndex:
    """Major-issue and offering filings of one company in a window.

    Attributes:
        filings (tuple[IndexedFiling, ...]): Filings read, newest first per group.
        incomplete (frozenset[IndexGroup]): Groups with more pages than were read.
    """

    filings: tuple[IndexedFiling, ...]
    incomplete: frozenset[IndexGroup] = frozenset()

    @property
    def complete(self) -> bool:
        """Whether every page of every group was read.

        Returns:
            bool: True when the index lists every filing in the window.
        """
        return not self.incomplete

    @property
    def kinds(self) -> frozenset[EventKind]:
        """Event kinds that may have reports in the window.

        These are the kinds seen, plus every kind of a group that was not read in full.

        Returns:
            frozenset[EventKind]: Kinds to read.
        """
        seen = {kind for filing in self.filings if (kind := filing.kind) is not None}
        resources = {GROUP_RESOURCES[group] for group in self.incomplete}
        unread = {kind for kind, spec in EVENT_KINDS.items() if spec.resource in resources}
        return frozenset(seen | unread)

    def titles(self) -> dict[str, str]:
        """Index titles by filing number.

        Returns:
            dict[str, str]: Filing number to title.
        """
        return {filing.filing_number: filing.title for filing in self.filings}

    def unstructured(self) -> tuple[IndexedFiling, ...]:
        """List major-issue filings that no structured service covers.

        Returns:
            tuple[IndexedFiling, ...]: Filings of group B whose titles map to no kind.
        """
        return tuple(f for f in self.filings if f.group == "B" and f.kind is None)


async def _page(
    state: AppState, company: Company, window: DateWindow, *, group: IndexGroup, page: int
) -> ListResponse | None:
    """Fetch one page of a company's filings in one group.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Filing date window.
        group (IndexGroup): Disclosure group.
        page (int): 1-based page number.

    Returns:
        ListResponse | None: The page, or None when the company filed nothing.
    """
    gateway = state.require_gateway()
    return await gateway.call(
        FILINGS,
        gateway.sdk.disclosures.search,
        corporation_code=company.corp_code,
        filing_start_date=yyyymmdd(window.start),
        filing_end_date=yyyymmdd(window.end),
        disclosure_category=group,
        page_number=page,
        page_size=PAGE_SIZE,
    )


def _filings(response: ListResponse | None, group: IndexGroup) -> list[IndexedFiling]:
    """Read the filings of one page.

    Args:
        response (ListResponse | None): Search page.
        group (IndexGroup): Disclosure group of the page.

    Returns:
        list[IndexedFiling]: Filings with a number and a title.
    """
    items = response.list or () if response else ()
    return [
        IndexedFiling(item.filing_number, clean_title(item.report_title), group)
        for item in items
        if item.filing_number and item.report_title
    ]


async def _group(
    state: AppState, company: Company, window: DateWindow, *, group: IndexGroup
) -> tuple[list[IndexedFiling], bool]:
    """Read up to MAX_PAGES pages of one group.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Filing date window.
        group (IndexGroup): Disclosure group.

    Returns:
        tuple[list[IndexedFiling], bool]: Filings and whether every page was read.
    """
    first = await _page(state, company, window, group=group, page=1)
    pages = (first.total_page or 1) if first else 1
    rest = await asyncio.gather(
        *(
            _page(state, company, window, group=group, page=number)
            for number in range(2, min(pages, MAX_PAGES) + 1)
        )
    )
    filings = [item for page in (first, *rest) for item in _filings(page, group)]
    return filings, pages <= MAX_PAGES


async def search_index(state: AppState, company: Company, window: DateWindow) -> EventIndex:
    """Search a company's major-issue and offering filings in a window.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Filing date window.

    Returns:
        EventIndex: Filings found and whether the index is complete.
    """
    groups = await asyncio.gather(
        *(_group(state, company, window, group=group) for group in INDEX_GROUPS)
    )
    filings = tuple(filing for found, _ in groups for filing in found)
    unread = frozenset(
        g for g, (_, complete) in zip(INDEX_GROUPS, groups, strict=True) if not complete
    )
    return EventIndex(filings, unread)
