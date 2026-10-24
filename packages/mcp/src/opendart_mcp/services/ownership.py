"""get_ownership: control snapshot, changes of control, and 5% holder and insider reports.

``opendart_analysis.ownership`` reads the snapshot from one periodic report: the largest
shareholder and related parties (``hyslr_sttus``), changes of the largest shareholder
(``hyslr_chg_sttus``), minority shareholders (``mrhl_sttus``, usually filed in annual reports
only), and share counts (``stock_totqy_sttus``). The period is the first candidate whose
largest-shareholder table has data. This adapter binds the tables to the gateway, shows the
snapshot (services.control) and the holding reports (services.holdings) as the output model,
and keeps the activity window's argument errors.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from opendart_analysis.domain.dates import DateWindow, parse_date_arg
from opendart_analysis.ownership import ownership_report
from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream_ownership import (
    control_changes_fetch,
    largest_holders_fetch,
    minority_holders_fetch,
    share_counts_fetch,
)
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.ownership import ControlChange, OwnershipResult
from opendart_mcp.services.control import snapshot_view
from opendart_mcp.services.holdings import holding_activity
from opendart_mcp.services.periods import PROBE_ATTEMPTS, resolve_period

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from opendart_analysis import ownership as analysis
    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Period
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.ownership import OwnershipSnapshot
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.holdings import Activity


@dataclass(frozen=True, slots=True)
class OwnershipQuery:
    """Arguments of get_ownership.

    Attributes:
        company (str): Name, stock code, or corp code.
        activity_window (str): Start of the holding-report window: ISO date or duration.
        period (Period): Periodic report for the snapshot.
        fiscal_year (int | None): Fiscal year, or None for the latest.
        detailed (bool): Whether to return every labeled field and more rows.
    """

    company: str
    activity_window: str = "180d"
    period: Period = "latest"
    fiscal_year: int | None = None
    detailed: bool = False


@dataclass(slots=True)
class _Periodic:
    """What the periodic report contributes to the result."""

    ref: PeriodRef | None = None
    period_end: date | None = None
    snapshot: OwnershipSnapshot | None = None
    changes: list[ControlChange] = field(default_factory=list)
    sources: list[SourceFiling] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


async def ownership(
    state: AppState, query: OwnershipQuery, *, progress: Progress = no_progress
) -> OwnershipResult:
    """Map control, changes of control, and holding reports for one company.

    Args:
        state (AppState): Server state.
        query (OwnershipQuery): Tool arguments.
        progress (Progress): Reports progress while the directory loads and data arrives.

    Returns:
        OwnershipResult: Snapshot, control changes, and holding reports in the window.

    Raises:
        InvalidArgumentError: The window or period cannot be used.
    """
    window = activity_window(query.activity_window, state.today())
    company = await state.companies.resolve(query.company, progress=progress)
    await progress(f"Reading ownership tables and holding reports of {company.ref.name}")
    periodic, activity = await asyncio.gather(
        _periodic(state, company, query),
        holding_activity(state, company, window, detailed=query.detailed, progress=progress),
    )
    return _result(company, periodic, activity, today=state.today())


def activity_window(text: str, today: date) -> DateWindow:
    """Resolve the activity window, which always ends today.

    Args:
        text (str): ISO date, or a duration back from today such as 180d.
        today (date): Today in KST.

    Returns:
        DateWindow: Window from the parsed date to today.

    Raises:
        InvalidArgumentError: The text is not a date or duration, or lies in the future.
    """
    try:
        start = parse_date_arg(text, today=today)
    except ValueError as error:
        message = f"activity_window: {error}."
        raise InvalidArgumentError(message) from error
    if start > today:
        message = f"activity_window {text!r} starts after today ({today.isoformat()}); pass a past date or a duration such as 180d."
        raise InvalidArgumentError(message)
    return DateWindow(start, today)


def _result(
    company: Company, periodic: _Periodic, activity: Activity, *, today: date
) -> OwnershipResult:
    """Assemble the tool result.

    Args:
        company (Company): Resolved company.
        periodic (_Periodic): Periodic-report part.
        activity (Activity): Holding-report part.
        today (date): Today in KST.

    Returns:
        OwnershipResult: Result model.
    """
    ref = periodic.ref
    return OwnershipResult(
        company=company.ref,
        as_of=today,
        source_filings=periodic.sources,
        notes=[*periodic.notes, *activity.notes],
        fiscal_year=ref.fiscal_year if ref else None,
        period=ref.period if ref else None,
        period_end=periodic.period_end,
        snapshot=periodic.snapshot,
        control_changes=periodic.changes,
        activity_since=activity.window.start,
        activity_until=activity.window.end,
        major_holder_reports=activity.major,
        major_holder_activity=activity.major_summary,
        insider_reports=activity.insider,
        insider_activity=activity.insider_summary,
    )


async def _periodic(state: AppState, company: Company, query: OwnershipQuery) -> _Periodic:
    """Read the ownership tables of the first candidate period that has them.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        query (OwnershipQuery): Tool arguments.

    Returns:
        _Periodic: Snapshot and control changes, or notes explaining their absence.
    """
    resolved = await resolve_period(
        state, company, period=query.period, fiscal_year=query.fiscal_year
    )
    notes = [resolved.note] if resolved.note else []
    report = await ownership_report(
        company,
        resolved,
        fetch_largest_holders=largest_holders_fetch(state.require_gateway),
        fetch_share_counts=share_counts_fetch(state.require_gateway),
        fetch_control_changes=control_changes_fetch(state.require_gateway),
        fetch_minority_holders=minority_holders_fetch(state.require_gateway),
        today=state.today(),
    )
    if report is None:
        tried = ", ".join(ref.label for ref in resolved.candidates[:PROBE_ATTEMPTS])
        notes.append(
            f"No periodic report for {tried} has a largest-shareholder table; unlisted and newly listed companies may not file one."
        )
        return _Periodic(notes=notes)
    snapshot, snapshot_notes = snapshot_view(report.snapshot, detailed=query.detailed)
    return _Periodic(
        ref=report.ref,
        period_end=report.period_end,
        snapshot=snapshot,
        changes=_control_changes(report.control_changes, detailed=query.detailed),
        sources=[SourceFiling.of(source.filing_number, source.title) for source in report.sources],
        notes=[*notes, *report.notes, *snapshot_notes],
    )


def _control_changes(
    changes: Iterable[analysis.ControlChange], *, detailed: bool
) -> list[ControlChange]:
    """Show changes of the largest shareholder, newest first.

    Concise results leave out notes, and with them changes that only have a note.

    Args:
        changes (Iterable[analysis.ControlChange]): Changes, newest first.
        detailed (bool): Whether to keep notes.

    Returns:
        list[ControlChange]: Changes.
    """
    shown = [
        ControlChange.model_validate(asdict(change) | ({} if detailed else {"note": None}))
        for change in changes
    ]
    return [change for change in shown if change.model_dump(exclude_none=True)]
