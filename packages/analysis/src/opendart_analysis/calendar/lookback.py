"""Which event reports a corporate-action calendar reads, and from when.

Schedules are announced weeks to a year before the dates themselves, so most kinds are read
from filings made in the year before the first calendar date (today unless the calendar
reaches into the past). Bond reports (``LONG_KINDS``) are read from three years before it: a
private placement opens conversion a year after payment, often more than a year after the
filing and later still when payment is postponed, and bonds mature years later. OpenDART
applies a window to the original filing date and folds amendments into the original row, so
a window never starts before 2015, when event reports begin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.catalog import kinds_in
from opendart_analysis.domain.dates import DateWindow, add_months
from opendart_analysis.events import CALENDAR_KINDS, EARLIEST

if TYPE_CHECKING:
    from datetime import date

    from opendart_analysis.catalog import EventKind

LOOKBACK_MONTHS: Final = 12
"""Months of event filings read before the first calendar date."""
LONG_LOOKBACK_MONTHS: Final = 36
"""Months of bond filings (LONG_KINDS) read before the first calendar date."""
LONG_KINDS: Final[frozenset[EventKind]] = (
    frozenset(kinds_in("convertible_and_hybrid_debt")) & CALENDAR_KINDS
)
"""Convertible, warrant, exchangeable, contingent capital, and debt offering reports."""
RECENT_KINDS: Final[frozenset[EventKind]] = CALENDAR_KINDS - LONG_KINDS
"""Kinds with calendar dates read over the shorter window."""


def lookback(start: date, today: date, months: int) -> DateWindow:
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
        recent = lookback(start, today, LOOKBACK_MONTHS)
        return cls(recent, lookback(start, today, LONG_LOOKBACK_MONTHS), kinds)

    @property
    def reads_recent(self) -> bool:
        """Whether kinds outside LONG_KINDS may be read, over the recent window.

        Returns:
            bool: True when the index chooses or a requested kind is outside LONG_KINDS.
        """
        return self.kinds is None or any(kind not in LONG_KINDS for kind in self.kinds)

    @property
    def reads_bonds(self) -> bool:
        """Whether LONG_KINDS may be read, over the extended window.

        Returns:
            bool: True when the index chooses or a requested kind is in LONG_KINDS.
        """
        return self.kinds is None or any(kind in LONG_KINDS for kind in self.kinds)
