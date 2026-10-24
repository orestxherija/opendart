"""Cache lifetimes, in seconds, by how often each kind of upstream data changes.

Periodic-report extracts, financial statements, and profiles change at most a few times a
year, so they are kept for a day. Filing lists and event reports change during the day.
Analysis workflows state how volatile the data they request is; ``lifetime`` maps that to
these values, so the cache policy stays in the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, assert_never

if TYPE_CHECKING:
    from opendart_analysis.upstream import Volatility

DAY: Final = 24 * 3600.0
"""Company profiles, periodic-report extracts, and financial statements."""

HOUR: Final = 3600.0
"""Major-issue and registration event reports for a date window."""

FILINGS: Final = 15 * 60.0
"""Filing searches, which change whenever a company files."""


def lifetime(volatility: Volatility) -> float:
    """Choose the cache lifetime for data an analysis workflow requests.

    Args:
        volatility (Volatility): How quickly the data can change.

    Returns:
        float: ``DAY`` for low, ``HOUR`` for medium, and ``FILINGS`` for high volatility.
    """
    match volatility:
        case "low":
            return DAY
        case "medium":
            return HOUR
        case "high":
            return FILINGS
        case _:
            assert_never(volatility)
