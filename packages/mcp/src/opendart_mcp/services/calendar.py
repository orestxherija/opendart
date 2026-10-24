"""get_corporate_action_calendar: forward corporate-action dates for a company or watchlist.

Assembling the calendar lives in ``opendart_analysis.calendar``: the window and kinds, the
lookback windows over which each company's event reports are read (a year before the first
date, three years for bond reports), event dates as items, merged repeats, and the order.
This adapter validates tool arguments, resolves the watchlist (asking about ambiguous names),
binds the reads to the gateway, bounds the work by a deadline, projects the analysis values
into the unchanged output model, caps it at ``MAX_ITEMS``, and words the notes.

Debt maturities are merged through an optional MaturityProvider: a coroutine function that
takes the state, one resolved company, and the calendar window, and returns calendar items
(action "debt_maturity") and notes, for example on what the items cover or why the source
was unavailable. It runs when kinds is None or names DEBT_KIND; items outside the window are
dropped, and its items merge with event maturities like the analysis reader's.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis import calendar
from opendart_analysis.calendar import (
    DEBT_KIND,
    MAX_COMPANIES,
    UndatedKindsError,
    UnknownKindsError,
)
from opendart_analysis.errors import AnalysisError
from opendart_mcp.core.errors import AmbiguousCompanyError, InvalidArgumentError, from_analysis
from opendart_mcp.core.interaction import choosing
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.core.upstream_filings import filing_pages
from opendart_mcp.models.calendar import CalendarResult
from opendart_mcp.services.calendar_items import analysis_item, output_item, subject
from opendart_mcp.services.calendar_reads import LONG_KINDS, source_note
from opendart_mcp.services.events import FOREGROUND_DEADLINE, READ_POLICY, bounded

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import date

    from opendart_analysis.calendar import CalendarSubject, CorporateActionCalendar, KindSelection
    from opendart_analysis.domain.dates import DateWindow
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.calendar import CalendarItem
    from opendart_mcp.services.companies import Company

type MaturityProvider = Callable[
    [AppState, Company, DateWindow], Awaitable[tuple[Sequence[CalendarItem], Sequence[str]]]
]
"""Debt maturity source: (state, company, calendar window) to calendar items and notes."""

__all__ = [
    "DEBT_KIND",
    "MAX_ITEMS",
    "CalendarRequest",
    "MaturityProvider",
    "action_calendar",
    "calendar_kinds",
    "resolve_companies",
]

MAX_ITEMS: Final = 200
"""Most items returned; the calendar app and the model read them all."""
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
class _Provided:
    """A maturity provider's answer, as ``opendart_analysis.calendar`` reads it.

    Attributes:
        items (tuple[calendar.CalendarItem, ...]): The provider's items.
        notes (tuple[str, ...]): The provider's notes.
    """

    items: tuple[calendar.CalendarItem, ...]
    notes: tuple[str, ...]


def calendar_kinds(kinds: Sequence[str] | None) -> KindSelection:
    """Validate requested kinds, keeping those whose reports have calendar dates.

    Args:
        kinds (Sequence[str] | None): Event groups or kinds, and DEBT_KIND; None or empty
            for all.

    Returns:
        KindSelection: Event kinds to read, whether to merge debt maturities, and the kinds
            left out.

    Raises:
        InvalidArgumentError: A name is unknown, or no requested kind has calendar dates.
    """
    try:
        return calendar.calendar_kinds(kinds)
    except UnknownKindsError as error:
        message = f"{error} See the opendart://reference/event-kinds resource."
        raise InvalidArgumentError(message) from error
    except UndatedKindsError as error:
        message = f"{", ".join(error.kinds)} reports carry no calendar dates; call get_corporate_events for them."
        raise InvalidArgumentError(message) from error


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


def _provider(
    state: AppState, provider: MaturityProvider, companies: Sequence[Company]
) -> Callable[[CalendarSubject, DateWindow], Awaitable[_Provided]]:
    """Adapt a maturity provider to ``opendart_analysis.calendar``'s maturity reader.

    Args:
        state (AppState): Server state.
        provider (MaturityProvider): Debt maturity source.
        companies (Sequence[Company]): Resolved companies, by which subjects are found.

    Returns:
        Callable[[CalendarSubject, DateWindow], Awaitable[_Provided]]: The reader.
    """
    by_code = {company.corp_code: company for company in companies}

    async def read(subject: CalendarSubject, window: DateWindow) -> _Provided:
        """Ask the provider for one company's maturities.

        Args:
            subject (CalendarSubject): Company.
            window (DateWindow): Calendar dates.

        Returns:
            _Provided: The provider's items and notes.
        """
        company = by_code[subject.corp_code]
        items, notes = await provider(state, company, window)
        return _Provided(tuple(analysis_item(item, company) for item in items), tuple(notes))

    return read


def _company_notes(found: CorporateActionCalendar[_Provided]) -> list[str]:
    """Describe each company's failures and debt coverage, in company order.

    Args:
        found (CorporateActionCalendar[_Provided]): Assembled calendar.

    Returns:
        list[str]: Notes.
    """
    notes: list[str] = []
    for company in found.companies:
        name = company.subject.name
        if company.error is not None:
            notes.append(f"No dates for {name}: {company.error}")
            continue
        if company.failed:
            notes.append(
                f"OpenDART did not answer for {name}'s {", ".join(company.failed)} reports."
            )
        notes.extend(() if company.maturities is None else company.maturities.notes)
    return notes


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
    span = _window(request, today)
    selection = calendar_kinds(request.kinds)
    resolved, merged = await resolve_companies(state, companies, progress=progress)
    provider = maturities if selection.debt else None
    work = calendar.corporate_action_calendar(
        [subject(company) for company in resolved],
        window=span,
        kinds=selection.events,
        maturities=None if provider is None else _provider(state, provider, resolved),
        fetch_service=service_fetch(state.require_gateway),
        read_filing_page=filing_pages(state.require_gateway),
        policy=READ_POLICY,
        max_companies=MAX_COMPANIES,
        today=today,
        progress=progress,
    )
    label = f"Reading event filings for {len(resolved)} companies"
    try:
        found = await bounded(work, progress, label=label, deadline=deadline)
    except AnalysisError as error:
        raise from_analysis(error) from error
    by_code = {company.corp_code: company for company in resolved}
    items = [output_item(item, by_code[item.corp_code]) for item in found.items]
    coverage = _coverage(found, selection, missing=selection.debt and maturities is None)
    notes = [*merged, *coverage, *_company_notes(found), *_tail(items, span)]
    return CalendarResult(
        as_of=today,
        start=span.start,
        end=span.end,
        horizon_days=(span.end - today).days,
        companies=[company.ref for company in resolved],
        items=items[:MAX_ITEMS],
        notes=list(dict.fromkeys(notes)),
    )


def _window(request: CalendarRequest, today: date) -> DateWindow:
    """Resolve the calendar's dates.

    Args:
        request (CalendarRequest): Validated tool arguments.
        today (date): Today in KST.

    Returns:
        DateWindow: From today or include_past to the horizon.

    Raises:
        InvalidArgumentError: horizon or include_past is invalid or on the wrong side of today.
    """
    try:
        return calendar.calendar_window(request.horizon, request.include_past, today=today)
    except AnalysisError as error:
        raise from_analysis(error) from error


def _coverage(
    found: CorporateActionCalendar[_Provided], selection: KindSelection, *, missing: bool
) -> list[str]:
    """Describe what the dates cover.

    Args:
        found (CorporateActionCalendar[_Provided]): Assembled calendar.
        selection (KindSelection): Kinds read and left out.
        missing (bool): Whether debt maturities were requested without a source.

    Returns:
        list[str]: Notes.
    """
    dropped = ", ".join(selection.dropped)
    notes = [f"Left out kinds without calendar dates: {dropped}."] if dropped else []
    if source := source_note(found.reads):
        notes.append(source)
    if missing:
        notes.append("Debt maturities are not included; see get_debt_profile.")
    if any(item.source_kind in LONG_KINDS for item in found.items):
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
