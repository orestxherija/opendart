"""A company's latest preliminary (unaudited) quarterly results, from KRX fair disclosures.

Listed companies publish preliminary results weeks before the quarterly report, in a KRX
fair disclosure titled "Report on Business Performance ... (Fair Disclosure)" (Korean
``영업(잠정)실적(공정공시)``). No structured service carries them, so the newest such
disclosure is found in the filing index, opened, and parsed with
``opendart_analysis.documents.extract_preliminary_earnings``.

Some filers, Samsung among them, first publish guidance with revenue and operating profit
only, then a complete release at month end; a correction of the guidance can be filed after
the complete release. The newest quarter wins, and within it a complete release wins.

Upstream quirk, verified live: the fair-disclosure subtype (``I002``) filters only when the
disclosure type is omitted, so the query names the subtype alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Protocol

from opendart_analysis.documents import extract_preliminary_earnings
from opendart_analysis.domain.filings import clean_title
from opendart_analysis.domain.identifiers import filing_date, is_filing_number
from opendart_analysis.financials.chain import no_progress
from opendart_analysis.upstream import MAX_FILING_PAGE

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from opendart_analysis.documents import ParsedFiling, PreliminaryEarnings
    from opendart_analysis.financials.chain import Progress
    from opendart_analysis.reports import FiscalCompany
    from opendart_analysis.upstream import FilingRecord, Volatility

FAIR_DISCLOSURE: Final = "I002"
"""Disclosure subtype (``pblntf_detail_ty``) of KRX fair disclosures."""
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


@dataclass(frozen=True, slots=True)
class DisclosureQuery:
    """One page of a company's final filings of one disclosure subtype, newest first.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        start (date): First filing date (KST), inclusive.
        end (date): Last filing date (KST), inclusive.
        subtype (str): Disclosure subtype (``pblntf_detail_ty``), such as ``I002``; the
            disclosure type is omitted, since OpenDART filters by subtype only without it.
        limit (int): Most filings to return, at most ``MAX_FILING_PAGE``.
    """

    corp_code: str
    start: date
    end: date
    subtype: str
    limit: int = MAX_FILING_PAGE


class SearchDisclosures(Protocol):
    """Search a company's final filings of one subtype; bound by the caller to a source."""

    async def __call__(
        self, query: DisclosureQuery, /, *, volatility: Volatility
    ) -> Sequence[FilingRecord] | None:
        """Return the final filings matching a query.

        Args:
            query (DisclosureQuery): Company, filing-date window, and subtype.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[FilingRecord] | None: Filings, newest first, or None when there are none.
        """
        ...


class OpenFiling(Protocol):
    """Download and parse one filing; bound by the caller to a source.

    A filed document does not change, so there is no volatility hint; a caching source can
    keep it indefinitely.
    """

    async def __call__(self, filing_number: str, /) -> ParsedFiling | None:
        """Return a parsed filing.

        Args:
            filing_number (str): 14-digit filing number.

        Returns:
            ParsedFiling | None: The filing, or None when it is unknown or cannot be read;
                the workflow then skips it with a note.
        """
        ...


@dataclass(frozen=True, slots=True)
class PreliminaryRelease:
    """Preliminary results and the fair disclosure they come from.

    Attributes:
        earnings (PreliminaryEarnings): Parsed figures, in won.
        filing_number (str): 14-digit filing number of the disclosure.
        title (str): Disclosure title, whitespace collapsed.
        notes (tuple[str, ...]): Newer disclosures that could not be used, and why.
    """

    earnings: PreliminaryEarnings
    filing_number: str
    title: str
    notes: tuple[str, ...] = ()


async def _candidates(
    company: FiscalCompany, *, search: SearchDisclosures, today: date
) -> list[tuple[str, str]]:
    """List the company's recent preliminary-earnings disclosures.

    Args:
        company (FiscalCompany): Company.
        search (SearchDisclosures): Filing search; asked with ``high`` volatility.
        today (date): Today in KST, which ends the search window.

    Returns:
        list[tuple[str, str]]: Filing numbers and titles, newest first; on the same day,
            consolidated results come before separate ones.
    """
    query = DisclosureQuery(company.corp_code, today - LOOKBACK, today, FAIR_DISCLOSURE)
    found = [
        (number, clean_title(row.report_title or ""))
        for row in await search(query, volatility="high") or ()
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
    candidate: tuple[str, str], *, open_filing: OpenFiling, notes: list[str], progress: Progress
) -> PreliminaryEarnings | None:
    """Open one disclosure and extract its results.

    Args:
        candidate (tuple[str, str]): Filing number and title.
        open_filing (OpenFiling): Downloads and parses the filing.
        notes (list[str]): Receives a note when the disclosure cannot be used.
        progress (Progress): Receives a message before the filing is opened.

    Returns:
        PreliminaryEarnings | None: The results, or None when the document is unavailable or
            does not use the preliminary-results template.
    """
    number, title = candidate
    await progress(f"Reading preliminary earnings in filing {number}")
    parsed = await open_filing(number)
    if parsed is None:
        notes.append(f"Filing {number} ({title}) could not be opened, so it was skipped.")
        return None
    earnings = extract_preliminary_earnings(parsed)
    if earnings is None:
        notes.append(f"Filing {number} ({title}) does not use the preliminary-results table.")
    return earnings


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


def _choose(
    best: PreliminaryRelease | None, release: PreliminaryRelease, notes: list[str]
) -> tuple[PreliminaryRelease, bool]:
    """Keep the better of the chosen release and an older one.

    Args:
        best (PreliminaryRelease | None): Release chosen so far, which reports no profit lines.
        release (PreliminaryRelease): Next readable release, older than ``best``.
        notes (list[str]): Receives a note when the older, complete release wins.

    Returns:
        tuple[PreliminaryRelease, bool]: The release to keep and whether the search is over.
    """
    if best is None:
        return release, _complete(release.earnings)
    if _same_quarter(best.earnings, release.earnings) and _complete(release.earnings):
        notes.append(
            f"Filing {best.filing_number} reports only revenue and operating profit; the complete release {release.filing_number} for the same quarter is used."
        )
        return release, True
    return best, True


async def latest_preliminary(
    company: FiscalCompany,
    *,
    search_disclosures: SearchDisclosures,
    open_filing: OpenFiling,
    today: date,
    progress: Progress | None = None,
) -> PreliminaryRelease | None:
    """Find and parse the company's newest preliminary-earnings fair disclosure.

    Searches one page of the last 120 days' fair disclosures and opens at most three, newest
    first, skipping ones that cannot be opened or do not use the preliminary-results
    template. When the newest release reports only revenue and operating profit, a complete
    release for the same quarter, if one was filed, is used instead.

    Args:
        company (FiscalCompany): Company.
        search_disclosures (SearchDisclosures): Filing search, called once with ``high``
            volatility.
        open_filing (OpenFiling): Downloads and parses one filing.
        today (date): Today in KST, which ends the search window.
        progress (Progress | None): Receives a message per disclosure opened.

    Returns:
        PreliminaryRelease | None: The figures and their filing, or None when the company
            published no readable preliminary results in the last 120 days.
    """
    report = progress or no_progress
    notes: list[str] = []
    best: PreliminaryRelease | None = None
    candidates = await _candidates(company, search=search_disclosures, today=today)
    for number, title in candidates[:MAX_CANDIDATES]:
        if best is not None and _apart(best.filing_number, number):
            break
        found = await _extract(
            (number, title), open_filing=open_filing, notes=notes, progress=report
        )
        if found is not None:
            best, done = _choose(best, PreliminaryRelease(found, number, title), notes)
            if done:
                break
    if best is None:
        return None
    return PreliminaryRelease(best.earnings, best.filing_number, best.title, tuple(notes))
