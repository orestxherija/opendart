"""get_corporate_events: material events from major-issue and registration reports.

Without categories, the company's filing index names the reports filed in the window and
only those services are read; when the index is too large to read in full, every service is
read, bounded by the gateway's concurrency. Rows are grouped by filing number. OpenDART
folds amendments into the original decision's row (latest filing number, amended terms) and
applies the window to the original filing date, so ``filed`` is the latest version's date.
Work is bounded by a deadline; calls already sent finish and land in the cache for a retry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Final

from opendart_mcp.core.errors import InvalidArgumentError, QuotaExhaustedError, UpstreamError
from opendart_mcp.core.progress import no_progress, with_heartbeat
from opendart_mcp.core.ttl import HOUR
from opendart_mcp.domain.dates import DateWindow, resolve_window, yyyymmdd
from opendart_mcp.events import records_from
from opendart_mcp.registry import EVENT_KINDS, expand, sdk_method
from opendart_mcp.services.event_index import search_index
from opendart_mcp.services.event_results import build_result

if TYPE_CHECKING:
    from collections.abc import Collection, Coroutine, Sequence

    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.events import EventRecord
    from opendart_mcp.models.events import CorporateEventsResult, Strategy
    from opendart_mcp.registry import EventKind
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.event_index import EventIndex
    from opendart_mcp.services.event_results import EventRequest

FOREGROUND_DEADLINE: Final = 40.0
"""Seconds a foreground call waits for upstream work before asking for a retry."""
BACKGROUND_DEADLINE: Final = 110.0
"""Seconds a background task waits for upstream work."""
DEFAULT_SINCE: Final = "1y"
EARLIEST: Final = date(2015, 1, 1)
"""First filing date of OpenDART's event reports."""


@dataclass(frozen=True, slots=True)
class EventBatch:
    """Event reports of one company in one window.

    Attributes:
        company (Company): Resolved company.
        window (DateWindow): Original filing date window.
        strategy (Strategy): How the kinds were chosen.
        queried (tuple[EventKind, ...]): Kinds read, in registry order.
        failed (tuple[EventKind, ...]): Kinds OpenDART did not answer.
        records (tuple[EventRecord, ...]): Records, newest filing first.
        index (EventIndex | None): Filing index, when it was searched.
    """

    company: Company
    window: DateWindow
    strategy: Strategy
    queried: tuple[EventKind, ...]
    failed: tuple[EventKind, ...]
    records: tuple[EventRecord, ...]
    index: EventIndex | None

    @property
    def with_data(self) -> tuple[EventKind, ...]:
        """Kinds that returned at least one event, in registry order.

        Returns:
            tuple[EventKind, ...]: Kinds with data.
        """
        found = {record.kind for record in self.records}
        return tuple(kind for kind in self.queried if kind in found)


def select_kinds(categories: Sequence[str] | None) -> tuple[EventKind, ...] | None:
    """Validate requested event groups and kinds.

    Args:
        categories (Sequence[str] | None): Group or kind names; None or empty for all.

    Returns:
        tuple[EventKind, ...] | None: Selected kinds, or None to let the index choose.

    Raises:
        InvalidArgumentError: A name is neither a group nor a kind.
    """
    if not categories:
        return None
    try:
        return expand(categories)
    except ValueError as error:
        message = f"{error} See the opendart://reference/event-kinds resource, or omit categories to read every kind the company filed."
        raise InvalidArgumentError(message) from error


def event_window(
    since: str | None, until: str | None, *, today: date
) -> tuple[DateWindow, list[str]]:
    """Resolve the filing date window, within what OpenDART covers.

    Args:
        since (str | None): Window start; None for the default year.
        until (str | None): Window end; None for today.
        today (date): Today in KST.

    Returns:
        tuple[DateWindow, list[str]]: Window from 2015 to today at most, and notes.

    Raises:
        InvalidArgumentError: The arguments are invalid or the window misses that range.
    """
    try:
        window = resolve_window(since, until, today=today, default_since=DEFAULT_SINCE)
    except ValueError as error:
        message = f"{error}."
        raise InvalidArgumentError(message) from error
    start, end = max(window.start, EARLIEST), min(window.end, today)
    if start > end:
        message = f"since and until ({window.start} to {window.end}) must overlap 2015-01-01 to today, the range of OpenDART's event reports."
        raise InvalidArgumentError(message)
    notes = (
        []
        if start == window.start
        else ["Event reports start in 2015; the window starts on 2015-01-01."]
    )
    return DateWindow(start, end), notes


async def _fetch_kind(
    state: AppState, company: Company, window: DateWindow, *, kind: EventKind
) -> tuple[EventRecord, ...]:
    """Read one event service for a company.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Original filing date window.
        kind (EventKind): Event kind to read.

    Returns:
        tuple[EventRecord, ...]: Records; empty when OpenDART has none.
    """
    gateway = state.require_gateway()
    response = await gateway.call(
        HOUR,
        sdk_method(gateway.sdk, EVENT_KINDS[kind].service),
        corporation_code=company.corp_code,
        filing_start_date=yyyymmdd(window.start),
        filing_end_date=yyyymmdd(window.end),
    )
    return () if response is None else tuple(records_from(kind, response))


def _split(
    kinds: Sequence[EventKind], outcomes: Sequence[tuple[EventRecord, ...] | BaseException]
) -> tuple[list[EventRecord], tuple[EventKind, ...]]:
    """Separate answers from failures, re-raising failures retries cannot fix.

    Args:
        kinds (Sequence[EventKind]): Kinds queried.
        outcomes (Sequence[tuple[EventRecord, ...] | BaseException]): Results in kind order.

    Returns:
        tuple[list[EventRecord], tuple[EventKind, ...]]: Records and kinds that failed.

    Raises:
        BaseException: The first failure other than an upstream error, such as an
            exhausted quota.
    """
    records: list[EventRecord] = []
    failed: list[EventKind] = []
    for kind, outcome in zip(kinds, outcomes, strict=True):
        if isinstance(outcome, UpstreamError) and not isinstance(outcome, QuotaExhaustedError):
            failed.append(kind)
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            records.extend(outcome)
    return records, tuple(failed)


async def _query(
    state: AppState,
    company: Company,
    window: DateWindow,
    *,
    kinds: Sequence[EventKind],
    progress: Progress,
) -> tuple[list[EventRecord], tuple[EventKind, ...]]:
    """Read several event services concurrently, reporting each answer.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Original filing date window.
        kinds (Sequence[EventKind]): Kinds to read.
        progress (Progress): Receives "3/12 event reports read" messages.

    Returns:
        tuple[list[EventRecord], tuple[EventKind, ...]]: Records and failed kinds.
    """
    done = 0

    async def one(kind: EventKind) -> tuple[EventRecord, ...]:
        """Read one event kind and report its completion.

        Args:
            kind (EventKind): Event service to query.

        Returns:
            tuple[EventRecord, ...]: Records returned by that service.
        """
        nonlocal done
        records = await _fetch_kind(state, company, window, kind=kind)
        done += 1
        await progress(f"{done}/{len(kinds)} event reports read ({kind})")
        return records

    outcomes = await asyncio.gather(*(one(kind) for kind in kinds), return_exceptions=True)
    return _split(kinds, outcomes)


async def _plan(
    state: AppState,
    company: Company,
    window: DateWindow,
    *,
    kinds: tuple[EventKind, ...] | None,
    restrict: Collection[EventKind] | None,
    progress: Progress,
) -> tuple[Strategy, tuple[EventKind, ...], EventIndex | None]:
    """Choose the kinds to read: the requested ones, or those in the filing index.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Original filing date window.
        kinds (tuple[EventKind, ...] | None): Requested kinds; None to use the index.
        restrict (Collection[EventKind] | None): With the index, only these kinds.
        progress (Progress): Receives a message before the search.

    Returns:
        tuple[Strategy, tuple[EventKind, ...], EventIndex | None]: Strategy, kinds in
            registry order, and the index when it was searched.
    """
    if kinds is not None:
        return "requested", kinds, None
    await progress(f"Searching {company.ref.name}'s major-issue and offering filings")
    index = await search_index(state, company, window)
    seen = index.kinds
    allowed = tuple(k for k in EVENT_KINDS if k in seen and (restrict is None or k in restrict))
    strategy: Strategy = "filing_index" if index.complete else "all_kinds"
    return strategy, allowed, index


async def fetch_events(
    state: AppState,
    company: Company,
    window: DateWindow,
    *,
    kinds: tuple[EventKind, ...] | None = None,
    restrict: Collection[EventKind] | None = None,
    progress: Progress = no_progress,
) -> EventBatch:
    """Read a company's event reports in a window.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Original filing date window.
        kinds (tuple[EventKind, ...] | None): Kinds to read; None lets the filing index
            choose.
        restrict (Collection[EventKind] | None): When the index chooses, only these kinds.
        progress (Progress): Receives progress messages.

    Returns:
        EventBatch: Records newest first, with coverage.
    """
    strategy, queried, index = await _plan(
        state, company, window, kinds=kinds, restrict=restrict, progress=progress
    )
    records, failed = await _query(state, company, window, kinds=queried, progress=progress)
    records.sort(key=lambda record: record.filing_number, reverse=True)
    return EventBatch(company, window, strategy, queried, failed, tuple(records), index)


async def bounded[T](
    work: Coroutine[Any, Any, T], progress: Progress, *, label: str, deadline: float
) -> T:
    """Run work with heartbeats, cancelling it at a deadline.

    Upstream calls already sent keep running in the gateway and fill the cache, so a retry
    after the deadline is fast.

    Args:
        work (Coroutine[Any, Any, T]): Work to run.
        progress (Progress): Receives a heartbeat every few seconds.
        label (str): What the work does, for messages.
        deadline (float): Seconds to wait.

    Returns:
        T: The work's result.
    """
    task = asyncio.ensure_future(work)
    try:
        return await with_heartbeat(task, progress, label=label, deadline=deadline)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.wait((task,))


async def corporate_events(
    state: AppState,
    company: str,
    *,
    request: EventRequest,
    progress: Progress = no_progress,
    deadline: float = FOREGROUND_DEADLINE,
) -> CorporateEventsResult:
    """Answer get_corporate_events.

    Args:
        state (AppState): Server state.
        company (str): Name, stock code, or corp code.
        request (EventRequest): Validated tool arguments.
        progress (Progress): Receives progress messages.
        deadline (float): Seconds to wait for upstream work.

    Returns:
        CorporateEventsResult: Events newest first, with coverage and notes.
    """
    kinds = select_kinds(request.categories)
    window, notes = event_window(request.since, request.until, today=state.today())
    resolved = await state.companies.resolve(company, progress=progress)
    work = fetch_events(state, resolved, window, kinds=kinds, progress=progress)
    label = f"Reading event reports for {resolved.ref.name}"
    batch = await bounded(work, progress, label=label, deadline=deadline)
    return build_result(state, batch, request=request, notes=notes)
