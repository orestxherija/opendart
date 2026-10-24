"""5% holder and insider ownership reports filed in an activity window.

``majorstock`` (significant holdings, the 5% rule) and ``elestock`` (executives and major
shareholders) take only the company and list about two years of filings, oldest first, with
filing dates as YYYY-MM-DD and signed changes such as ``-348,407``. A large company has
thousands of insider reports, so reports are filtered to the window by filing date, sorted
newest first, and bounded, while the activity counts cover every report in the window.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from opendart_analysis.domain.dates import add_months
from opendart_analysis.domain.identifiers import filing_date, is_filing_number
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date, parse_percent
from opendart_mcp.core.errors import StillRunningError
from opendart_mcp.core.progress import no_progress, with_heartbeat
from opendart_mcp.core.ttl import HOUR
from opendart_mcp.models.ownership import InsiderReport, MajorHolderReport, ReportActivity
from opendart_mcp.services.shares import items_of, trim

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date

    from pydantic import BaseModel

    from opendart.models.equity_disclosures import (
        ElestockResponseListItem,
        MajorstockResponseListItem,
    )
    from opendart_analysis.domain.dates import DateWindow
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company

MAJOR_LIMIT: Final = 10
"""Most 5% holder reports in a concise result."""
INSIDER_LIMIT: Final = 15
"""Most insider reports in a concise result."""
DETAILED_LIMIT: Final = 100
"""Most reports of each kind in a detailed result."""
LISTING_MONTHS: Final = 24
# OpenDART can take over a minute to send a large company's full holding-report history.
# Past this deadline the snapshot is returned without the lists, which finish in the cache.
ACTIVITY_DEADLINE: Final = 25.0
PENDING_NOTE: Final = "5% holder and insider reports are still downloading: OpenDART sends long histories slowly. Retry in about a minute; the download continues and will be cached."
"""OpenDART lists holding reports from about the last two years only."""

_MAJOR_STATUS: Final = {
    "10%이상주주": "Shareholders holding 10% or more",
    "사실상지배주주": "Effective controlling shareholders",
    "주요주주": "Major shareholder",
}
_UNREGISTERED: Final = ("unregistered", "비등기", "미등기")
_REGISTERED: Final = ("registered", "등기")
# search_filings categories that list every report of each kind.
_CATEGORIES: Final = {
    "5% holder reports": "major_holding_report",
    "insider reports": "insider_ownership_report",
}
_MAJOR_DETAIL: Final = ("contract_shares", "contract_pct")
_INSIDER_DETAIL: Final = ("change_pct",)


@dataclass(frozen=True, slots=True)
class Activity:
    """Holding reports in the window and what they add up to.

    Attributes:
        window (DateWindow): Filing-date window.
        major (list[MajorHolderReport]): 5% holder reports shown, newest first.
        major_summary (ReportActivity | None): Counts over every 5% holder report in the
            window; None while the reports are still downloading.
        insider (list[InsiderReport]): Insider reports shown, newest first.
        insider_summary (ReportActivity | None): Counts over every insider report in the
            window; None while the reports are still downloading.
        notes (list[str]): Truncation and coverage notes.
    """

    window: DateWindow
    major: list[MajorHolderReport]
    major_summary: ReportActivity | None
    insider: list[InsiderReport]
    insider_summary: ReportActivity | None
    notes: list[str]


class _Dated(Protocol):
    """A holding report with a filing date and number."""

    @property
    def filed(self) -> date | None:
        """Filing date.

        Returns:
            date | None: Date on which the report was filed, when known.
        """
        ...

    @property
    def filing_number(self) -> str:
        """Filing number.

        Returns:
            str: Filing number assigned to the report.
        """
        ...


async def holding_activity(
    state: AppState,
    company: Company,
    window: DateWindow,
    *,
    detailed: bool,
    progress: Progress = no_progress,
    deadline: float = ACTIVITY_DEADLINE,
) -> Activity:
    """List the 5% holder and insider reports filed in a window (two upstream calls).

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Filing-date window.
        detailed (bool): Whether to show more reports with every labeled field.
        progress (Progress): Reports elapsed time while the lists download.
        deadline (float): Seconds to wait before answering without the lists.

    Returns:
        Activity: Reports shown and counts over the window, or a pending note.
    """
    gateway = state.require_gateway()
    equity = gateway.sdk.equity_disclosures
    work = asyncio.gather(
        gateway.call(HOUR, equity.majorstock, corporation_code=company.corp_code),
        gateway.call(HOUR, equity.elestock, corporation_code=company.corp_code),
    )
    # The downloads may outlive this call; retrieve a late failure so it is not reported
    # as unhandled. The gateway caches successful answers for the retry.
    work.add_done_callback(lambda done: done.cancelled() or done.exception())
    try:
        major, insider = await with_heartbeat(
            work, progress, label="Downloading 5% holder and insider reports", deadline=deadline
        )
    except StillRunningError:
        return Activity(window, [], None, [], None, [PENDING_NOTE])
    majors = _recent(
        (_major(item, n) for item in items_of(major) if (n := _number(item.filing_number))), window
    )
    insiders = _recent(
        (_insider(item, n) for item in items_of(insider) if (n := _number(item.filing_number))),
        window,
    )
    major_limit = DETAILED_LIMIT if detailed else MAJOR_LIMIT
    insider_limit = DETAILED_LIMIT if detailed else INSIDER_LIMIT
    shown_major = _shown(majors, limit=major_limit, detail=_MAJOR_DETAIL, detailed=detailed)
    shown_insider = _shown(insiders, limit=insider_limit, detail=_INSIDER_DETAIL, detailed=detailed)
    notes = (
        _bounded("5% holder reports", window, total=len(majors), shown=len(shown_major)),
        _bounded("insider reports", window, total=len(insiders), shown=len(shown_insider)),
        _horizon(window),
    )
    return Activity(
        window=window,
        major=shown_major,
        major_summary=_summary([r.change_in_shares for r in majors], len(shown_major)),
        insider=shown_insider,
        insider_summary=_summary([r.change for r in insiders], len(shown_insider)),
        notes=[note for note in notes if note is not None],
    )


def _number(text: str | None) -> str | None:
    """Return a well-formed filing number.

    Args:
        text (str | None): Filing number as listed.

    Returns:
        str | None: The 14-digit number, or None when missing or malformed.
    """
    number = clean_text(text)
    return number if number is not None and is_filing_number(number) else None


def _major(item: MajorstockResponseListItem, number: str) -> MajorHolderReport:
    """Parse one 5% holder report.

    Args:
        item (MajorstockResponseListItem): Upstream row.
        number (str): Its filing number.

    Returns:
        MajorHolderReport: Report with signed changes.
    """
    return MajorHolderReport(
        filed=parse_date(item.filing_date) or filing_date(number),
        filing_number=number,
        reporter=clean_text(item.repror),
        report_type=clean_text(item.report_tp),
        shares=parse_amount(item.stkqy),
        change_in_shares=parse_amount(item.stkqy_irds),
        pct=_pct(item.stkrt),
        change_in_pct=_pct(item.stkrt_irds),
        reason=_reason(item.report_resn),
        contract_shares=parse_amount(item.ctr_stkqy),
        contract_pct=_pct(item.ctr_stkrt),
    )


def _insider(item: ElestockResponseListItem, number: str) -> InsiderReport:
    """Parse one executive or major-shareholder ownership report.

    Args:
        item (ElestockResponseListItem): Upstream row.
        number (str): Its filing number.

    Returns:
        InsiderReport: Report with signed changes.
    """
    return InsiderReport(
        filed=parse_date(item.filing_date) or filing_date(number),
        filing_number=number,
        reporter=clean_text(item.repror),
        position=clean_text(item.isu_exctv_ofcps),
        is_registered_officer=_registered(item.isu_exctv_rgist_at),
        major_shareholder=_major_status(item.isu_main_shrholdr),
        shares=parse_amount(item.sp_stock_lmp_cnt),
        change=parse_amount(item.sp_stock_lmp_irds_cnt),
        pct=_pct(item.sp_stock_lmp_rate),
        change_pct=_pct(item.sp_stock_lmp_irds_rate),
    )


def _recent[R: _Dated](rows: Iterable[R], window: DateWindow) -> list[R]:
    """Keep reports filed in the window, newest first.

    Args:
        rows (Iterable[R]): Parsed reports.
        window (DateWindow): Filing-date window.

    Returns:
        list[R]: Reports in the window; filing numbers start with the date, so they order
            reports by date and by sequence within a day.
    """
    kept = [
        row for row in rows if row.filed is not None and window.start <= row.filed <= window.end
    ]
    return sorted(kept, key=lambda row: row.filing_number, reverse=True)


def _shown[R: BaseModel](
    rows: Sequence[R], *, limit: int, detail: tuple[str, ...], detailed: bool
) -> list[R]:
    """Bound the reports shown; concise results drop detail fields.

    Args:
        rows (Sequence[R]): Reports, newest first.
        limit (int): Most reports to show.
        detail (tuple[str, ...]): Fields only detailed results carry.
        detailed (bool): Whether the result is detailed.

    Returns:
        list[R]: Reports to show.
    """
    head = list(rows[:limit])
    return head if detailed else [trim(row, detail) for row in head]


def _summary(changes: Sequence[int | None], shown: int) -> ReportActivity:
    """Count reports by direction of the reported change.

    Args:
        changes (Sequence[int | None]): Share change of every report in the window.
        shown (int): Reports shown.

    Returns:
        ReportActivity: Counts and the net change.
    """
    known = [change for change in changes if change]
    return ReportActivity(
        reports=len(changes),
        shown=shown,
        increases=sum(1 for change in known if change > 0),
        decreases=sum(1 for change in known if change < 0),
        net_change=sum(known),
    )


def _bounded(noun: str, window: DateWindow, *, total: int, shown: int) -> str | None:
    """Say how to see reports beyond the bound.

    Args:
        noun (str): Kind of report, plural: a key of the search_filings categories table.
        window (DateWindow): Filing-date window.
        total (int): Reports in the window.
        shown (int): Reports shown.

    Returns:
        str | None: Note, or None when every report is shown.
    """
    if total <= shown:
        return None
    category = _CATEGORIES[noun]
    return f"Showing the {shown} newest of {total} {noun} filed since {window.start.isoformat()}; narrow activity_window, or call search_filings with category {category} to list them all."


def _horizon(window: DateWindow) -> str | None:
    """Warn that OpenDART's holding-report listings stop about two years back.

    Args:
        window (DateWindow): Filing-date window.

    Returns:
        str | None: Note when the window starts earlier than the listings reach.
    """
    if window.start >= add_months(window.end, -LISTING_MONTHS):
        return None
    return "OpenDART lists holding reports from about the last two years only; call search_filings with category major_holding_report or insider_ownership_report for older ones."


def _pct(text: str | None) -> float | None:
    """Parse a percentage, writing upstream's "-0.00" as 0.0.

    Args:
        text (str | None): Raw percentage.

    Returns:
        float | None: Percentage, or None for blanks and dashes.
    """
    value = parse_percent(text)
    # Adding 0.0 turns -0.0 into 0.0 and leaves every other value unchanged.
    return None if value is None else value + 0.0


def _reason(text: str | None) -> str | None:
    """Join a bulleted, multi-line reason into one line.

    Args:
        text (str | None): Reason as filed: lines such as "- 보유주식수 변동".

    Returns:
        str | None: Items separated by semicolons, or None when blank.
    """
    items = (clean_text(line.strip().lstrip("-·•")) for line in (text or "").splitlines())
    return "; ".join(item for item in items if item) or None


def _registered(text: str | None) -> bool | None:
    """Read whether an insider is a registered (board) officer.

    Args:
        text (str | None): Status as filed, such as "Unregistered executive" or 등기임원.

    Returns:
        bool | None: True for registered officers, False for unregistered ones, None when
            the reporter is not an officer or the status is blank.
    """
    folded = (clean_text(text) or "").casefold()
    if any(word in folded for word in _UNREGISTERED):
        return False
    return True if any(word in folded for word in _REGISTERED) else None


def _major_status(text: str | None) -> str | None:
    """Translate a major-shareholder status.

    Args:
        text (str | None): Status as filed, English or Korean.

    Returns:
        str | None: English status, the filed text when unknown, or None when blank.
    """
    cleaned = clean_text(text)
    return _MAJOR_STATUS.get("".join(cleaned.split()), cleaned) if cleaned else None
