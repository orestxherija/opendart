"""get_ownership: control snapshot, changes of control, and 5% holder and insider reports.

The snapshot comes from one periodic report: the largest shareholder and related parties
(``hyslr_sttus``), changes of the largest shareholder (``hyslr_chg_sttus``), minority
shareholders (``mrhl_sttus``, usually filed in annual reports only), and share counts
(``stock_totqy_sttus``). The period is the first candidate whose largest-shareholder table
has data. Holding reports (``majorstock``, ``elestock``) come from services.holdings.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.progress import no_progress
from opendart_mcp.domain.dates import DateWindow, parse_date_arg
from opendart_mcp.domain.identifiers import is_filing_number
from opendart_mcp.domain.normalize import clean_text, parse_amount, parse_date, parse_percent
from opendart_mcp.domain.periods import PeriodRef
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.ownership import ControlChange, Minority, OwnershipResult
from opendart_mcp.services.control import build_snapshot
from opendart_mcp.services.holdings import holding_activity
from opendart_mcp.services.periods import (
    PROBE_ATTEMPTS,
    first_available,
    periodic_ttl,
    resolve_period,
)
from opendart_mcp.services.shares import (
    blank,
    fetch_share_counts,
    period_args,
    report_rows,
    trim,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from opendart.models.periodic_reports import (
        HyslrChgSttusResponseListItem,
        HyslrSttusResponseListItem,
        MrhlSttusResponseListItem,
    )
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.types import Period
    from opendart_mcp.models.ownership import OwnershipSnapshot
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.holdings import Activity
    from opendart_mcp.services.periods import ResolvedPeriod

    type FoundMinority = tuple[Minority, PeriodRef, str | None]


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
    found = await first_available(resolved, lambda ref: _holder_rows(state, company, ref))
    part = _Periodic(notes=[resolved.note] if resolved.note else [])
    if found is None:
        tried = ", ".join(ref.label for ref in resolved.candidates[:PROBE_ATTEMPTS])
        part.notes.append(
            f"No periodic report for {tried} has a largest-shareholder table; unlisted and newly listed companies may not file one."
        )
        return part
    ref, items = found
    reports = state.require_gateway().sdk.periodic_reports
    counts, changes, minority = await asyncio.gather(
        fetch_share_counts(state, company, ref),
        report_rows(
            state,
            reports.hyslr_chg_sttus,
            period_args(company, ref),
            ttl=periodic_ttl(state, company, ref),
        ),
        _minority(state, company, ref),
    )
    part.ref, part.period_end = ref, ref.end_date or parse_date(items[0].stlm_dt)
    part.changes = _control_changes(changes, detailed=query.detailed)
    _cite(part, items[0].filing_number, _title(resolved, ref))
    if ref != resolved.candidates[0]:
        part.notes.append(
            f"The {resolved.candidates[0].label} report has no ownership tables yet; showing {ref.label}."
        )
    figures = _minority_part(part, minority, detailed=query.detailed)
    part.snapshot, notes = build_snapshot(items, counts, figures, detailed=query.detailed)
    part.notes.extend(notes)
    return part


async def _holder_rows(
    state: AppState, company: Company, ref: PeriodRef
) -> list[HyslrSttusResponseListItem] | None:
    """Fetch the largest-shareholder table of one period.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Candidate period.

    Returns:
        list[HyslrSttusResponseListItem] | None: Named rows, or None when there are none.
    """
    method = state.require_gateway().sdk.periodic_reports.hyslr_sttus
    ttl = periodic_ttl(state, company, ref)
    items = await report_rows(state, method, period_args(company, ref), ttl=ttl)
    return [item for item in items if clean_text(item.nm)] or None


async def _minority(state: AppState, company: Company, ref: PeriodRef) -> FoundMinority | None:
    """Fetch minority shareholders, falling back to the prior annual report.

    Quarterly and half-year reports usually omit the minority-shareholder table.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Period of the snapshot.

    Returns:
        FoundMinority | None: Figures, the period they come from, and its filing number;
            None when neither report has them.
    """
    method = state.require_gateway().sdk.periodic_reports.mrhl_sttus
    fallback = PeriodRef(ref.fiscal_year - 1, "FY")
    for candidate in (ref,) if ref.period == "FY" else (ref, fallback):
        ttl = periodic_ttl(state, company, candidate)
        items = await report_rows(state, method, period_args(company, candidate), ttl=ttl)
        rows = [(_minority_row(item), item.filing_number) for item in items]
        found = next(((row, number) for row, number in rows if not blank(row, "as_of")), None)
        if found is not None:
            return found[0], candidate, found[1]
    return None


def _minority_row(item: MrhlSttusResponseListItem) -> Minority:
    """Parse the minority-shareholder row.

    Args:
        item (MrhlSttusResponseListItem): Upstream row.

    Returns:
        Minority: Holder and share counts with their percentages.
    """
    return Minority(
        holders=parse_amount(item.shrholdr_co),
        total_holders=parse_amount(item.shrholdr_tot_co),
        holder_pct=parse_percent(item.shrholdr_rate),
        shares=parse_amount(item.hold_stock_co),
        share_pct=parse_percent(item.hold_stock_rate),
        total_shares=parse_amount(item.stock_tot_co),
        as_of=parse_date(item.stlm_dt),
    )


def _minority_part(
    part: _Periodic, found: FoundMinority | None, *, detailed: bool
) -> Minority | None:
    """Pick the minority figures, citing and noting a fallback report.

    Args:
        part (_Periodic): Periodic part being built; its ref is set.
        found (FoundMinority | None): Figures and their source.
        detailed (bool): Whether to keep the total share count.

    Returns:
        Minority | None: Figures for the snapshot.
    """
    if found is None:
        return None
    minority, ref, number = found
    if ref != part.ref:
        part.notes.append(
            f"Minority shareholder figures come from the {ref.label} annual report; quarterly and half-year reports usually omit them."
        )
        _cite(part, number, None)
    return minority if detailed else trim(minority, ("total_shares",))


def _control_changes(
    items: Iterable[HyslrChgSttusResponseListItem], *, detailed: bool
) -> list[ControlChange]:
    """Parse changes of the largest shareholder, newest first, without rows of dashes.

    Args:
        items (Iterable[HyslrChgSttusResponseListItem]): Upstream rows.
        detailed (bool): Whether to keep notes.

    Returns:
        list[ControlChange]: Changes.
    """
    changes = [
        ControlChange(
            date=parse_date(item.change_on),
            new_largest_shareholder=clean_text(item.mxmm_shrholdr_nm),
            shares=parse_amount(item.posesn_stock_co),
            pct=parse_percent(item.qota_rt),
            cause=clean_text(item.change_cause),
            note=clean_text(item.rm) if detailed else None,
        )
        for item in items
    ]
    kept = [change for change in changes if not blank(change)]
    return sorted(kept, key=lambda c: c.date.toordinal() if c.date else 0, reverse=True)


def _title(resolved: ResolvedPeriod, ref: PeriodRef) -> str | None:
    """Return the periodic report's title when the filing index named it.

    Args:
        resolved (ResolvedPeriod): Period resolution.
        ref (PeriodRef): Period used.

    Returns:
        str | None: Report title, or None when unknown.
    """
    report = resolved.report
    return report.title if report is not None and report.ref == ref else None


def _cite(part: _Periodic, filing_number: str | None, title: str | None) -> None:
    """Add a periodic report to the sources, once.

    Args:
        part (_Periodic): Periodic part being built.
        filing_number (str | None): Filing number from the rows.
        title (str | None): Report title, when known.
    """
    number = clean_text(filing_number)
    cited = {source.filing_number for source in part.sources}
    if number is not None and is_filing_number(number) and number not in cited:
        part.sources.append(SourceFiling.of(number, title))
