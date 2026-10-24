"""5% holder and insider ownership reports filed in an activity window.

``majorstock`` (significant holdings, the 5% rule) and ``elestock`` (executives and major
shareholders) take only the company and list about two years of filings, oldest first, with
filing dates as YYYY-MM-DD and signed changes such as ``-348,407``. A large company has
thousands of insider reports. ``opendart_analysis.ownership`` filters them to the window by
filing date, newest first, and counts them; here the lists are bounded, concise results drop
detail fields, and a slow download is answered without them after a deadline.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.ownership import holding_reports, predates_listings
from opendart_mcp.core.errors import StillRunningError
from opendart_mcp.core.progress import no_progress, with_heartbeat
from opendart_mcp.core.upstream_ownership import insider_holdings_fetch, major_holdings_fetch
from opendart_mcp.models.ownership import InsiderReport, MajorHolderReport, ReportActivity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from _typeshed import DataclassInstance

    from opendart_analysis import ownership
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
# OpenDART can take over a minute to send a large company's full holding-report history.
# Past this deadline the snapshot is returned without the lists, which finish in the cache.
ACTIVITY_DEADLINE: Final = 25.0
PENDING_NOTE: Final = "5% holder and insider reports are still downloading: OpenDART sends long histories slowly. Retry in about a minute; the download continues and will be cached."

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
    work = asyncio.ensure_future(
        holding_reports(
            company.corp_code,
            since=window.start,
            fetch_major_holdings=major_holdings_fetch(state.require_gateway),
            fetch_insider_holdings=insider_holdings_fetch(state.require_gateway),
            today=window.end,
        )
    )
    # The downloads may outlive this call; retrieve a late failure so it is not reported
    # as unhandled. The gateway caches successful answers for the retry.
    work.add_done_callback(lambda done: done.cancelled() or done.exception())
    try:
        reports = await with_heartbeat(
            work, progress, label="Downloading 5% holder and insider reports", deadline=deadline
        )
    except StillRunningError:
        return Activity(window, [], None, [], None, [PENDING_NOTE])
    major_limit = DETAILED_LIMIT if detailed else MAJOR_LIMIT
    insider_limit = DETAILED_LIMIT if detailed else INSIDER_LIMIT
    shown_major = [
        MajorHolderReport.model_validate(_shown(report, _MAJOR_DETAIL, detailed=detailed))
        for report in reports.major[:major_limit]
    ]
    shown_insider = [
        InsiderReport.model_validate(_shown(report, _INSIDER_DETAIL, detailed=detailed))
        for report in reports.insider[:insider_limit]
    ]
    notes = (
        _bounded("5% holder reports", window, total=len(reports.major), shown=len(shown_major)),
        _bounded("insider reports", window, total=len(reports.insider), shown=len(shown_insider)),
        _horizon(window),
    )
    return Activity(
        window=window,
        major=shown_major,
        major_summary=_summary(reports.major_activity, len(shown_major)),
        insider=shown_insider,
        insider_summary=_summary(reports.insider_activity, len(shown_insider)),
        notes=[note for note in notes if note is not None],
    )


def _shown(
    report: DataclassInstance, detail: Sequence[str], *, detailed: bool
) -> dict[str, object]:
    """Read a report's fields, without those that only detailed results carry.

    Args:
        report (DataclassInstance): Report.
        detail (Sequence[str]): Fields only detailed results carry.
        detailed (bool): Whether the result is detailed.

    Returns:
        dict[str, object]: Fields to show.
    """
    fields = asdict(report)
    return fields if detailed else fields | dict.fromkeys(detail)


def _summary(counts: ownership.ReportActivity, shown: int) -> ReportActivity:
    """Show the counts over every report in the window with the number shown.

    Args:
        counts (ownership.ReportActivity): Counts by direction of the reported change.
        shown (int): Reports shown.

    Returns:
        ReportActivity: Counts and the net change.
    """
    return ReportActivity(
        reports=counts.reports,
        shown=shown,
        increases=counts.increases,
        decreases=counts.decreases,
        net_change=counts.net_change,
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
    if not predates_listings(window.start, window.end):
        return None
    return "OpenDART lists holding reports from about the last two years only; call search_filings with category major_holding_report or insider_ownership_report for older ones."
