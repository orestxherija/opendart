"""get_corporate_action_calendar: forward corporate-action dates for a company or watchlist.

Each company's event reports are read through the events service, as calendar_reads plans:
schedules (subscriptions, record dates, listings, conversion windows, meetings, suspensions)
are announced weeks to a year before the dates themselves, bond schedules years before, and
amended rows carry the latest dates. Only kinds whose reports have calendar dates are read.

Debt maturities are merged through an optional MaturityProvider: a coroutine function that
takes the state, one resolved company, and the calendar window, and returns calendar items
(action "debt_maturity") and notes, for example on what the items cover or why the source
was unavailable. It runs when kinds is None or names DEBT_KIND; items outside the window are
dropped. calendar_items merges dates that a registration statement repeats from its
decision, and event maturities that a debt maturity repeats.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_mcp.core.errors import (
    AmbiguousCompanyError,
    InvalidArgumentError,
    QuotaExhaustedError,
    UpstreamError,
)
from opendart_mcp.core.interaction import choosing
from opendart_mcp.core.progress import no_progress
from opendart_mcp.domain.dates import DateWindow, parse_date_arg, parse_horizon
from opendart_mcp.events import ACTIONS, CALENDAR_KINDS
from opendart_mcp.models.calendar import CalendarResult
from opendart_mcp.registry import expand
from opendart_mcp.services.calendar_items import event_items, merge_maturities
from opendart_mcp.services.calendar_reads import LONG_KINDS, Reads, read_events
from opendart_mcp.services.events import FOREGROUND_DEADLINE, bounded

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import date

    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.calendar import CalendarItem
    from opendart_mcp.registry import EventKind
    from opendart_mcp.services.companies import Company

type MaturityProvider = Callable[
    [AppState, Company, DateWindow], Awaitable[tuple[Sequence[CalendarItem], Sequence[str]]]
]
"""Debt maturity source: (state, company, calendar window) to calendar items and notes."""

DEBT_KIND: Final = "debt_maturity"
"""Calendar-only kind that selects the maturity provider's debt maturities."""
MAX_ITEMS: Final = 200
"""Most items returned; the calendar app and the model read them all."""
_ACTION_ORDER: Final = {code: index for index, code in enumerate(ACTIONS)}
_AS_FILED: Final = "Conversion, exercise, exchange, and maturity dates of bonds are as filed at issuance; bonds converted or redeemed early still show them."


@dataclass(frozen=True, slots=True)
class CalendarRequest:
    """Validated arguments of get_corporate_action_calendar.

    Attributes:
        horizon (str): Last date, as an ISO date or a forward duration.
        include_past (str | None): First date when earlier than today, as an ISO date or a
            backward duration; None starts today.
        kinds (tuple[str, ...] | None): Event groups or kinds, and DEBT_KIND; None for
            every kind with calendar dates and debt maturities.
    """

    horizon: str = "90d"
    include_past: str | None = None
    kinds: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class KindSelection:
    """What a calendar request reads.

    Attributes:
        events (tuple[EventKind, ...] | None): Event kinds; None lets each company's filing
            index choose; empty reads no event reports.
        debt (bool): Whether to merge debt maturities.
        notes (tuple[str, ...]): Notes about kinds left out.
    """

    events: tuple[EventKind, ...] | None
    debt: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Plan:
    """What to read for every company.

    Attributes:
        span (DateWindow): Calendar dates to keep.
        reads (Reads): Event reports to read.
        maturities (MaturityProvider | None): Debt maturity source, when requested.
    """

    span: DateWindow
    reads: Reads
    maturities: MaturityProvider | None


def _horizon(text: str, today: date) -> date:
    """Parse the forward horizon.

    Args:
        text (str): ISO date or forward duration, such as 90d.
        today (date): Today in KST.

    Returns:
        date: Last calendar date.

    Raises:
        InvalidArgumentError: The horizon is invalid or in the past.
    """
    try:
        end = parse_horizon(text, today=today)
    except ValueError as error:
        message = f"horizon: {error}."
        raise InvalidArgumentError(message) from error
    if end < today:
        message = f"horizon ({end}) is before today ({today}); pass a forward duration such as 90d, and include_past for earlier dates."
        raise InvalidArgumentError(message)
    return end


def _start(text: str | None, today: date) -> date:
    """Parse include_past.

    Args:
        text (str | None): ISO date or backward duration, such as 30d; None for today.
        today (date): Today in KST.

    Returns:
        date: First calendar date.

    Raises:
        InvalidArgumentError: The value is invalid or after today.
    """
    if text is None:
        return today
    try:
        start = parse_date_arg(text, today=today)
    except ValueError as error:
        message = f"include_past: {error}."
        raise InvalidArgumentError(message) from error
    if start > today:
        message = f"include_past ({start}) is after today ({today}); pass a past date or a duration such as 30d."
        raise InvalidArgumentError(message)
    return start


def calendar_kinds(kinds: Sequence[str] | None) -> KindSelection:
    """Validate requested kinds, keeping those whose reports have calendar dates.

    Args:
        kinds (Sequence[str] | None): Event groups or kinds, and DEBT_KIND; None or empty
            for all.

    Returns:
        KindSelection: Event kinds to read, whether to merge debt maturities, and notes
            about kinds left out.

    Raises:
        InvalidArgumentError: A name is unknown, or no requested kind has calendar dates.
    """
    if not kinds:
        return KindSelection(None, debt=True)
    names = [name for name in kinds if name != DEBT_KIND]
    debt = len(names) < len(kinds)
    if not names:
        return KindSelection((), debt=debt)
    try:
        selected = expand(names)
    except ValueError as error:
        message = f"{error} The calendar also accepts {DEBT_KIND}. See the opendart://reference/event-kinds resource."
        raise InvalidArgumentError(message) from error
    kept = tuple(kind for kind in selected if kind in CALENDAR_KINDS)
    dropped = [kind for kind in selected if kind not in CALENDAR_KINDS]
    if not kept and not debt:
        message = f"{", ".join(dropped)} reports carry no calendar dates; call get_corporate_events for them."
        raise InvalidArgumentError(message)
    note = f"Left out kinds without calendar dates: {", ".join(dropped)}."
    return KindSelection(kept, debt=debt, notes=(note,) if dropped else ())


async def _settle(
    state: AppState, name: str, outcome: Company | BaseException, *, progress: Progress
) -> Company:
    """Finish resolving one company after the concurrent first pass.

    Args:
        state (AppState): Server state.
        name (str): Company text as given.
        outcome (Company | BaseException): First-pass result.
        progress (Progress): Receives directory progress.

    Returns:
        Company: The company.

    Raises:
        BaseException: The first-pass failure, or the ambiguity left after asking.
    """
    if isinstance(outcome, AmbiguousCompanyError):
        return await state.companies.resolve(name, progress=progress)
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome


async def resolve_companies(
    state: AppState, names: Sequence[str], *, progress: Progress = no_progress
) -> tuple[list[Company], list[str]]:
    """Resolve a watchlist, merging duplicates.

    Names resolve concurrently without asking the user; ambiguous ones are then resolved
    one at a time, so a host that supports elicitation asks about each in turn.

    Args:
        state (AppState): Server state.
        names (Sequence[str]): Company names or codes.
        progress (Progress): Receives directory progress.

    Returns:
        tuple[list[Company], list[str]]: Companies in input order and notes.
    """
    with choosing(None):
        first = await asyncio.gather(
            *(state.companies.resolve(name, progress=progress) for name in names),
            return_exceptions=True,
        )
    unique: dict[str, Company] = {}
    for name, outcome in zip(names, first, strict=True):
        company = await _settle(state, name, outcome, progress=progress)
        unique.setdefault(company.corp_code, company)
    merged = len(names) - len(unique)
    return list(unique.values()), [f"Merged {merged} duplicate companies."] if merged else []


async def _maturities(
    state: AppState, company: Company, plan: _Plan
) -> tuple[Sequence[CalendarItem], Sequence[str]]:
    """Ask the maturity provider for one company's debt maturities within the span.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        plan (_Plan): What to read.

    Returns:
        tuple[Sequence[CalendarItem], Sequence[str]]: Items within the span and notes.
    """
    if plan.maturities is None:
        return (), ()
    items, notes = await plan.maturities(state, company, plan.span)
    return [item for item in items if plan.span.start <= item.date <= plan.span.end], notes


async def _company_items(
    state: AppState, company: Company, plan: _Plan
) -> tuple[list[CalendarItem], list[str]]:
    """Collect one company's calendar items, reading events and debt concurrently.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        plan (_Plan): What to read.

    Returns:
        tuple[list[CalendarItem], list[str]]: Items and notes.

    Raises:
        BaseException: The first failure of either read, after both have finished.
    """
    batches, maturities = await asyncio.gather(
        read_events(state, company, plan.reads),
        _maturities(state, company, plan),
        return_exceptions=True,
    )
    if isinstance(batches, BaseException):
        raise batches
    if isinstance(maturities, BaseException):
        raise maturities
    debt, debt_notes = maturities
    records = [record for batch in batches for record in batch.records]
    items = merge_maturities(event_items(company, records, plan.span), debt)
    failed = ", ".join(kind for batch in batches for kind in batch.failed)
    notes = (
        [f"OpenDART did not answer for {company.ref.name}'s {failed} reports."] if failed else []
    )
    return items, [*notes, *debt_notes]


async def _collect(
    state: AppState, companies: Sequence[Company], plan: _Plan, *, progress: Progress
) -> tuple[list[CalendarItem], list[str]]:
    """Collect every company's items concurrently, reporting each company.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Resolved companies.
        plan (_Plan): What to read.
        progress (Progress): Receives "7/20 Samsung Electronics" messages.

    Returns:
        tuple[list[CalendarItem], list[str]]: Items and notes.

    Raises:
        BaseException: A failure other than an upstream error for one company.
    """
    done = 0

    async def one(company: Company) -> tuple[list[CalendarItem], list[str]]:
        """Collect one company's calendar entries and report its completion.

        Args:
            company (Company): Resolved company to read.

        Returns:
            tuple[list[CalendarItem], list[str]]: Calendar entries and their notes.
        """
        nonlocal done
        found = await _company_items(state, company, plan)
        done += 1
        await progress(f"{done}/{len(companies)} {company.ref.name}")
        return found

    outcomes = await asyncio.gather(*(one(c) for c in companies), return_exceptions=True)
    items: list[CalendarItem] = []
    notes: list[str] = []
    for company, outcome in zip(companies, outcomes, strict=True):
        if isinstance(outcome, UpstreamError) and not isinstance(outcome, QuotaExhaustedError):
            notes.append(f"No dates for {company.ref.name}: {outcome}")
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            items.extend(outcome[0])
            notes.extend(outcome[1])
    return items, notes


def _sort_key(item: CalendarItem) -> tuple[date, str, int, str]:
    """Order items by date, company, action, and filing.

    Args:
        item (CalendarItem): Calendar item.

    Returns:
        tuple[date, str, int, str]: Sort key.
    """
    order = _ACTION_ORDER.get(item.action, len(_ACTION_ORDER))
    return item.date, item.company.name, order, item.filing_number


async def action_calendar(
    state: AppState,
    companies: Sequence[str],
    *,
    request: CalendarRequest,
    progress: Progress = no_progress,
    deadline: float = FOREGROUND_DEADLINE,
    maturities: MaturityProvider | None = None,
) -> CalendarResult:
    """Answer get_corporate_action_calendar.

    Args:
        state (AppState): Server state.
        companies (Sequence[str]): Company names or codes.
        request (CalendarRequest): Validated tool arguments.
        progress (Progress): Receives progress messages.
        deadline (float): Seconds to wait for upstream work.
        maturities (MaturityProvider | None): Debt maturity source to merge.

    Returns:
        CalendarResult: Items sorted by date, capped at MAX_ITEMS.
    """
    today = state.today()
    span = DateWindow(_start(request.include_past, today), _horizon(request.horizon, today))
    selection = calendar_kinds(request.kinds)
    resolved, merged = await resolve_companies(state, companies, progress=progress)
    reads = Reads.before(span.start, today=today, kinds=selection.events)
    plan = _Plan(span, reads, maturities if selection.debt else None)
    label = f"Reading event filings for {len(resolved)} companies"
    items, found = await bounded(
        _collect(state, resolved, plan, progress=progress), progress, label=label, deadline=deadline
    )
    items.sort(key=_sort_key)
    missing = selection.debt and maturities is None
    coverage = _coverage(items, plan, missing=missing)
    notes = [*merged, *selection.notes, *coverage, *found, *_tail(items, span)]
    return CalendarResult(
        as_of=today,
        start=span.start,
        end=span.end,
        horizon_days=(span.end - today).days,
        companies=[company.ref for company in resolved],
        items=items[:MAX_ITEMS],
        notes=list(dict.fromkeys(notes)),
    )


def _coverage(items: Sequence[CalendarItem], plan: _Plan, *, missing: bool) -> list[str]:
    """Describe what the dates cover.

    Args:
        items (Sequence[CalendarItem]): Every item found.
        plan (_Plan): What was read.
        missing (bool): Whether debt maturities were requested without a source.

    Returns:
        list[str]: Notes.
    """
    source = plan.reads.note()
    notes = [source] if source else []
    if missing:
        notes.append("Debt maturities are not included; see get_debt_profile.")
    if any(item.source_kind in LONG_KINDS for item in items):
        notes.append(_AS_FILED)
    return notes


def _tail(items: Sequence[CalendarItem], span: DateWindow) -> list[str]:
    """Describe emptiness and truncation.

    Args:
        items (Sequence[CalendarItem]): Every item found.
        span (DateWindow): Calendar dates kept.

    Returns:
        list[str]: Notes.
    """
    if not items:
        return [f"No corporate-action dates from {span.start} to {span.end}."]
    if len(items) > MAX_ITEMS:
        return [
            f"Showing the first {MAX_ITEMS} of {len(items)} dates; shorten the horizon or pass fewer companies or kinds."
        ]
    return []
