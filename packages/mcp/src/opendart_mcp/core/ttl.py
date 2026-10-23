"""Cache lifetimes, in seconds, by how often each kind of upstream data changes.

Periodic-report extracts, financial statements, and profiles change at most a few times a
year, so they are kept for a day. Filing lists and event reports change during the day.
"""

from __future__ import annotations

from typing import Final

DAY: Final = 24 * 3600.0
"""Company profiles, periodic-report extracts, and financial statements."""

HOUR: Final = 3600.0
"""Major-issue and registration event reports for a date window."""

FILINGS: Final = 15 * 60.0
"""Filing searches, which change whenever a company files."""

NONE: Final = 0.0
"""Do not cache."""
