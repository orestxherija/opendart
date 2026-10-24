"""get_corporate_events: material events from major-issue and registration reports.

Reading and interpreting events lives in ``opendart_analysis.events``: without categories,
the company's filing index names the reports filed in the window and only those services are
read; when the index is too large to read in full, every service of the unread group is read,
bounded by the gateway's concurrency. This adapter validates tool arguments, binds the reads
to the gateway, treats upstream failures other than an exhausted quota as failed kinds, and
bounds the work by a deadline; calls already sent finish and land in the cache for a retry.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

from opendart_analysis import events
from opendart_analysis.catalog import expand
from opendart_analysis.domain.dates import resolve_window
from opendart_analysis.events import EARLIEST, EventBatch, EventQuery, ReadPolicy, covered_window
from opendart_mcp.core.errors import InvalidArgumentError, QuotaExhaustedError, UpstreamError
from opendart_mcp.core.progress import no_progress, with_heartbeat
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.core.upstream_filings import filing_pages
from opendart_mcp.services.event_index import MAX_PAGES
from opendart_mcp.services.event_results import build_result

if TYPE_CHECKING:
    from collections.abc import Collection, Coroutine, Sequence
    from datetime import date

    from opendart_analysis.catalog import EventKind
    from opendart_analysis.domain.dates import DateWindow
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.events import CorporateEventsResult
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.event_results import EventRequest

__all__ = [
    "BACKGROUND_DEADLINE",
    "DEFAULT_SINCE",
    "EARLIEST",
    "FOREGROUND_DEADLINE",
    "READ_POLICY",
    "EventBatch",
    "bounded",
    "corporate_events",
    "event_window",
    "fetch_events",
    "select_kinds",
]

FOREGROUND_DEADLINE: Final = 40.0
"""Seconds a foreground call waits for upstream work before asking for a retry."""
BACKGROUND_DEADLINE: Final = 110.0
"""Seconds a background task waits for upstream work."""
DEFAULT_SINCE: Final = "1y"


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
    covered = covered_window(window, today=today)
    if covered is None:
        message = f"since and until ({window.start} to {window.end}) must overlap 2015-01-01 to today, the range of OpenDART's event reports."
        raise InvalidArgumentError(message)
    notes = (
        []
        if covered.start == window.start
        else ["Event reports start in 2015; the window starts on 2015-01-01."]
    )
    return covered, notes


def _failed_kind(error: BaseException) -> bool:
    """Treat an upstream failure as a failed kind, unless retrying cannot help.

    Args:
        error (BaseException): Failure of one event service read.

    Returns:
        bool: True for upstream errors other than an exhausted quota.
    """
    return isinstance(error, UpstreamError) and not isinstance(error, QuotaExhaustedError)


READ_POLICY: Final = ReadPolicy(tolerate=_failed_kind, max_index_pages=MAX_PAGES)
"""Upstream failures other than an exhausted quota become failed kinds (and failed companies in
the calendar); the gateway bounds concurrency."""


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
    query = EventQuery(
        company.corp_code,
        window,
        kinds=kinds,
        restrict=None if restrict is None else frozenset(restrict),
        name=company.ref.name,
    )
    return await events.fetch_events(
        query,
        fetch_service=service_fetch(state.require_gateway),
        read_filing_page=filing_pages(state.require_gateway),
        policy=READ_POLICY,
        progress=progress,
    )


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
    return build_result(state, batch, company=resolved.ref, request=request, notes=notes)
