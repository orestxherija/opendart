"""A company's latest preliminary (unaudited) quarterly results, from KRX fair disclosures.

Listed companies publish preliminary results weeks before the quarterly report, in a KRX
fair disclosure titled "Report on Business Performance ... (Fair Disclosure)" (Korean
``영업(잠정)실적(공정공시)``). No structured service carries them, so the newest such
disclosure is found in the filing index, opened through the document store, and parsed.
``get_financials(view="preliminary")`` builds on :func:`latest_preliminary`.

Some filers, Samsung among them, first publish guidance with revenue and operating profit
only, then a complete release at month end; a correction of the guidance can be filed after
the complete release. The newest quarter wins, and within it a complete release wins.

Upstream quirk, verified live: the fair-disclosure subtype (``I002``) filters only when the
group code is omitted, so the search sends the subtype alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from opendart_analysis.documents import extract_preliminary_earnings
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.ttl import FILINGS
from opendart_mcp.domain.dates import yyyymmdd
from opendart_mcp.domain.filings import clean_title
from opendart_mcp.domain.identifiers import filing_date, is_filing_number
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.preliminary import PreliminaryResult
from opendart_mcp.services.documents import (
    DocumentUnavailableError,
    UnknownFilingError,
    load_filing,
    wait_seconds,
)

if TYPE_CHECKING:
    from opendart_analysis.documents import PreliminaryEarnings
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company

LOOKBACK: Final = timedelta(days=120)
"""How far back to look: one quarter plus the reporting lag."""
MAX_CANDIDATES: Final = 3
"""Disclosures opened at most, newest first."""
SAME_QUARTER: Final = timedelta(days=60)
"""Older disclosures are another quarter: guidance and complete results come weeks apart."""
_TITLE: Final = re.compile(r"business\s+performance|잠정\s*\)?\s*실적", re.IGNORECASE)
_CONSOLIDATED: Final = re.compile(r"consolidated|연결", re.IGNORECASE)
_PROFIT_LINES: Final = frozenset(
    {"pretax_profit", "net_profit", "net_profit_attributable_to_owners"}
)


async def _candidates(state: AppState, company: Company) -> list[tuple[str, str]]:
    """List the company's recent preliminary-earnings disclosures.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.

    Returns:
        list[tuple[str, str]]: Filing numbers and titles, newest first; on the same day,
            consolidated results come before separate ones.
    """
    gateway = state.require_gateway()
    today = state.today()
    response = await gateway.call(
        FILINGS,
        gateway.sdk.disclosures.search,
        corporation_code=company.corp_code,
        filing_start_date=yyyymmdd(today - LOOKBACK),
        filing_end_date=yyyymmdd(today),
        final_reports_only="Y",
        disclosure_subcategory="I002",
        page_size=100,
    )
    found = [
        (number, clean_title(row.report_title or ""))
        for row in (response.list or [] if response else [])
        if is_filing_number(number := (row.filing_number or "").strip())
        and _TITLE.search(row.report_title or "")
    ]
    return sorted(
        found,
        key=lambda entry: (entry[0][:8], bool(_CONSOLIDATED.search(entry[1])), entry[0]),
        reverse=True,
    )


def _complete(earnings: PreliminaryEarnings) -> bool:
    """Check whether a release reports profit beyond revenue and operating profit.

    Args:
        earnings (PreliminaryEarnings): Extracted release.

    Returns:
        bool: True when pretax or net profit is reported for the quarter.
    """
    return any(
        row.metric in _PROFIT_LINES and row.current_quarter.krw is not None for row in earnings.rows
    )


def _same_quarter(first: PreliminaryEarnings, second: PreliminaryEarnings) -> bool:
    """Check whether two releases cover the same quarter.

    Args:
        first (PreliminaryEarnings): One release.
        second (PreliminaryEarnings): Another release.

    Returns:
        bool: True when both state the same current-quarter end date.
    """
    ends = [
        next((p.end for p in release.periods if p.key == "current_quarter"), None)
        for release in (first, second)
    ]
    return ends[0] is not None and ends[0] == ends[1]


async def _extract(
    state: AppState, candidate: tuple[str, str], *, notes: list[str], progress: Progress
) -> PreliminaryEarnings | None:
    """Open one disclosure and extract its results.

    Args:
        state (AppState): Server state.
        candidate (tuple[str, str]): Filing number and title.
        notes (list[str]): Receives a note when the disclosure cannot be used.
        progress (Progress): Receives a message and download heartbeats.

    Returns:
        PreliminaryEarnings | None: The results, or None when the document is unavailable or
            does not use the preliminary-results template.
    """
    number, title = candidate
    await progress(f"Reading preliminary earnings in filing {number}")
    try:
        parsed = await load_filing(
            state, number, wait_s=wait_seconds(state, background=False), progress=progress
        )
    except UnknownFilingError, DocumentUnavailableError:
        notes.append(f"Filing {number} ({title}) could not be opened, so it was skipped.")
        return None
    earnings = extract_preliminary_earnings(parsed)
    if earnings is None:
        notes.append(f"Filing {number} ({title}) does not use the preliminary-results table.")
    return earnings


@dataclass(frozen=True, slots=True)
class _Release:
    """An extracted release and its filing."""

    earnings: PreliminaryEarnings
    number: str
    title: str


def _apart(newer: str, older: str) -> bool:
    """Check whether two disclosures were filed too far apart to cover the same quarter.

    Args:
        newer (str): Filing number of the newer disclosure.
        older (str): Filing number of the older disclosure.

    Returns:
        bool: True when more than 60 days separate them.
    """
    first, second = filing_date(newer), filing_date(older)
    return first is not None and second is not None and first - second > SAME_QUARTER


def _choose(best: _Release | None, release: _Release, notes: list[str]) -> tuple[_Release, bool]:
    """Keep the better of the chosen release and an older one.

    Args:
        best (_Release | None): Release chosen so far, which reports no profit lines.
        release (_Release): Next readable release, older than ``best``.
        notes (list[str]): Receives a note when the older, complete release wins.

    Returns:
        tuple[_Release, bool]: The release to keep and whether the search is over.
    """
    if best is None:
        return release, _complete(release.earnings)
    if _same_quarter(best.earnings, release.earnings) and _complete(release.earnings):
        notes.append(
            f"Filing {best.number} reports only revenue and operating profit; the complete release {release.number} for the same quarter is used."
        )
        return release, True
    return best, True


async def latest_preliminary(
    state: AppState, company: Company, *, progress: Progress = no_progress
) -> PreliminaryResult | None:
    """Find and parse the company's newest preliminary-earnings fair disclosure.

    Looks back 120 days and opens at most three disclosures, newest first, skipping ones
    whose document is unavailable or does not use the preliminary-results template. When
    the newest release reports only revenue and operating profit, a complete release for the
    same quarter, if one was filed, is used instead.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        progress (Progress): Receives a message per disclosure opened and while downloading.

    Returns:
        PreliminaryResult | None: The figures and their source filing, or None when the
            company published no readable preliminary results in the last 120 days.

    Raises:
        StillRunningError: A download outlived the foreground wait; retry shortly.
        UpstreamError: OpenDART failed, for example with the daily quota exhausted.
    """
    notes: list[str] = []
    best: _Release | None = None
    for number, title in (await _candidates(state, company))[:MAX_CANDIDATES]:
        if best is not None and _apart(best.number, number):
            break
        earnings = await _extract(state, (number, title), notes=notes, progress=progress)
        if earnings is not None:
            best, done = _choose(best, _Release(earnings, number, title), notes)
            if done:
                break
    if best is None:
        return None
    source = SourceFiling.of(best.number, best.title)
    return PreliminaryResult(earnings=best.earnings, source=source, notes=notes)
