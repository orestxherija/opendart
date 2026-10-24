"""Which event reports the corporate-action calendar reads, and the note that says so.

The lookback windows (a year before the first calendar date, three years for bond reports),
the filing-index search that serves both, and the reads themselves live in
``opendart_analysis.calendar``; the calendar adapter binds them to the gateway. This module
re-exports the windows and words the note on which filings the dates come from.
"""

from __future__ import annotations

from opendart_analysis.calendar import LONG_KINDS, LONG_LOOKBACK_MONTHS, LOOKBACK_MONTHS, Reads

__all__ = ["LONG_KINDS", "LONG_LOOKBACK_MONTHS", "LOOKBACK_MONTHS", "Reads", "source_note"]


def source_note(reads: Reads) -> str | None:
    """Say which filings the event dates come from.

    Args:
        reads (Reads): Event reports read.

    Returns:
        str | None: The note, or None when no event reports are read.
    """
    recent, bonds = reads.reads_recent, reads.reads_bonds
    if recent and bonds:
        return f"Dates come from major-issue and registration filings made since {reads.recent.start} and, for convertible, warrant, exchangeable, and other bonds, since {reads.extended.start}."
    if recent:
        return (
            f"Dates come from major-issue and registration filings made since {reads.recent.start}."
        )
    if bonds:
        return f"Dates come from convertible, warrant, exchangeable, and other bond filings made since {reads.extended.start}."
    return None
