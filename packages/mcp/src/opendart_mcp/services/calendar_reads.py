"""Which event reports the corporate-action calendar reads, and from when.

Schedules are announced weeks to a year before the dates themselves, so most kinds are read
from filings made in the year before the first calendar date (today unless include_past).
Bond reports (LONG_KINDS) are read from three years before it: a private placement opens
conversion a year after payment, often more than a year after the filing and later still
when payment is postponed, and bonds mature years later. OpenDART applies a window to the
original filing date and folds amendments into the original row. When the filing index picks
the kinds, one search over the longer window serves both windows, so the longer window costs
no extra search: a kind outside LONG_KINDS is read only when the index lists one of its
filings since the shorter window's start.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.dates import DateWindow, add_months
from opendart_mcp.domain.identifiers import filing_date
from opendart_mcp.events import CALENDAR_KINDS
from opendart_mcp.registry import EVENT_KINDS, kinds_in
from opendart_mcp.services.event_index import GROUP_RESOURCES, search_index
from opendart_mcp.services.events import EARLIEST, fetch_events
from opendart_mcp.services.extracts import gather_all

if TYPE_CHECKING:
    from opendart_mcp.core.state import AppState
    from opendart_mcp.registry import EventKind
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.event_index import EventIndex
    from opendart_mcp.services.events import EventBatch

LOOKBACK_MONTHS: Final = 12
"""Months of event filings read before the first calendar date."""
LONG_LOOKBACK_MONTHS: Final = 36
"""Months of bond filings (LONG_KINDS) read before the first calendar date."""
LONG_KINDS: Final[frozenset[EventKind]] = (
    frozenset(kinds_in("convertible_and_hybrid_debt")) & CALENDAR_KINDS
)
"""Convertible, warrant, exchangeable, contingent capital, and debt offering reports."""
_RECENT_KINDS: Final = CALENDAR_KINDS - LONG_KINDS


def _window(start: date, today: date, months: int) -> DateWindow:
    """Choose original filing dates to read.

    Args:
        start (date): First calendar date.
        today (date): Today in KST.
        months (int): Months to read before the first calendar date.

    Returns:
        DateWindow: From that many months before the start, but not before 2015, to today.
    """
    return DateWindow(max(add_months(start, -months), EARLIEST), today)


@dataclass(frozen=True, slots=True)
class Reads:
    """Event reports to read for every company.

    Attributes:
        recent (DateWindow): Original filing dates read for most kinds.
        extended (DateWindow): Original filing dates read for LONG_KINDS.
        kinds (tuple[EventKind, ...] | None): Requested kinds; None lets each company's
            filing index choose; empty reads none.
    """

    recent: DateWindow
    extended: DateWindow
    kinds: tuple[EventKind, ...] | None

    @classmethod
    def before(cls, start: date, *, today: date, kinds: tuple[EventKind, ...] | None) -> Reads:
        """Plan the reads for a calendar that starts on a date.

        Args:
            start (date): First calendar date.
            today (date): Today in KST.
            kinds (tuple[EventKind, ...] | None): Requested kinds, or None for the index.

        Returns:
            Reads: Windows of LOOKBACK_MONTHS and LONG_LOOKBACK_MONTHS before the start.
        """
        recent = _window(start, today, LOOKBACK_MONTHS)
        return cls(recent, _window(start, today, LONG_LOOKBACK_MONTHS), kinds)

    def note(self) -> str | None:
        """Say which filings the event dates come from.

        Returns:
            str | None: The note, or None when no event reports are read.
        """
        kinds = self.kinds
        recent = kinds is None or any(kind not in LONG_KINDS for kind in kinds)
        bonds = kinds is None or any(kind in LONG_KINDS for kind in kinds)
        if recent and bonds:
            return f"Dates come from major-issue and registration filings made since {self.recent.start} and, for convertible, warrant, exchangeable, and other bonds, since {self.extended.start}."
        if recent:
            return f"Dates come from major-issue and registration filings made since {self.recent.start}."
        if bonds:
            return f"Dates come from convertible, warrant, exchangeable, and other bond filings made since {self.extended.start}."
        return None


def _filed_since(index: EventIndex, since: date) -> frozenset[EventKind]:
    """List the kinds that the filing index shows filed since a date.

    Every kind of a group the index could not read in full counts as filed, as in the
    events service.

    Args:
        index (EventIndex): Filing index.
        since (date): First filing date.

    Returns:
        frozenset[EventKind]: Kinds to read.
    """
    resources = {GROUP_RESOURCES[group] for group in index.incomplete}
    partial = {kind for kind, spec in EVENT_KINDS.items() if spec.resource in resources}
    dated = {
        kind
        for filing in index.filings
        if (kind := filing.kind) is not None
        and (filing_date(filing.filing_number) or date.min) >= since
    }
    return frozenset(partial | dated)


async def _indexed(
    state: AppState, company: Company, reads: Reads
) -> tuple[tuple[EventKind, ...], tuple[EventKind, ...]]:
    """Pick the kinds to read from one filing-index search over the extended window.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        reads (Reads): Windows to read.

    Returns:
        tuple[tuple[EventKind, ...], tuple[EventKind, ...]]: Kinds filed since the recent
            window's start, and LONG_KINDS filed since the extended window's start, each in
            registry order.
    """
    index = await search_index(state, company, reads.extended)
    recent, seen = _filed_since(index, reads.recent.start), index.kinds
    return (
        tuple(k for k in EVENT_KINDS if k in recent and k in _RECENT_KINDS),
        tuple(k for k in EVENT_KINDS if k in seen and k in LONG_KINDS),
    )


async def read_events(state: AppState, company: Company, reads: Reads) -> list[EventBatch]:
    """Read one company's event reports: LONG_KINDS over the extended window, others recently.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        reads (Reads): What to read.

    Returns:
        list[EventBatch]: One batch per window read.
    """
    if reads.kinds is None:
        recent, extended = await _indexed(state, company, reads)
    else:
        recent = tuple(kind for kind in reads.kinds if kind not in LONG_KINDS)
        extended = tuple(kind for kind in reads.kinds if kind in LONG_KINDS)
    windows = ((reads.recent, recent), (reads.extended, extended))
    return await gather_all(
        fetch_events(state, company, window, kinds=kinds) for window, kinds in windows if kinds
    )
