"""Read a company's material events from major-issue and registration reports.

Without requested kinds, the company's filing index names the reports filed in the window
and only those services are read; when the index is too large to read in full, every service
of the unread group is read. Rows are grouped by filing number (``records_from``). OpenDART
folds amendments into the original decision's row (latest filing number, amended terms) and
applies the window to the original filing date, so a record's filing number is its latest
version's. Records come back newest filing first.

Services are read concurrently, at most ``concurrency`` at a time when given. A service whose
call fails with an exception the caller's ``tolerate`` accepts is reported in ``failed``
instead of failing the read; any other exception propagates unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.catalog import EVENT_KINDS
from opendart_analysis.domain.dates import DateWindow, yyyymmdd
from opendart_analysis.errors import DataSourceError
from opendart_analysis.events.index import MAX_PAGES, search_index
from opendart_analysis.events.records import records_from
from opendart_analysis.upstream import no_progress

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from opendart_analysis.catalog import EventKind
    from opendart_analysis.events.index import EventIndex
    from opendart_analysis.events.records import EventRecord
    from opendart_analysis.filings.access import ReadFilingPage
    from opendart_analysis.upstream import FetchService, Progress

type Strategy = Literal["requested", "filing_index", "all_kinds"]
"""How the kinds read were chosen: as requested, from a complete filing index, or from an
incomplete one, which adds every kind of each group it could not read in full."""

EARLIEST: Final = date(2015, 1, 1)
"""First filing date of OpenDART's event reports."""


@dataclass(frozen=True, slots=True)
class EventBatch:
    """Event reports of one company in one window.

    Attributes:
        corp_code (str): DART corporation code read.
        window (DateWindow): Original filing date window.
        strategy (Strategy): How the kinds were chosen.
        queried (tuple[EventKind, ...]): Kinds read, in catalog order.
        failed (tuple[EventKind, ...]): Kinds whose service failed with a tolerated error.
        records (tuple[EventRecord, ...]): Records, newest filing first.
        index (EventIndex | None): Filing index, when it was searched.
    """

    corp_code: str
    window: DateWindow
    strategy: Strategy
    queried: tuple[EventKind, ...]
    failed: tuple[EventKind, ...]
    records: tuple[EventRecord, ...]
    index: EventIndex | None

    @property
    def with_data(self) -> tuple[EventKind, ...]:
        """Kinds that returned at least one event, in catalog order.

        Returns:
            tuple[EventKind, ...]: Kinds with data.
        """
        found = {record.kind for record in self.records}
        return tuple(kind for kind in self.queried if kind in found)

    def titles(self) -> dict[str, str]:
        """Filing index titles by filing number, for ``amendment_flag``.

        Returns:
            dict[str, str]: Titles; empty when the index was not searched.
        """
        return self.index.titles() if self.index else {}


def covered_window(window: DateWindow, *, today: date) -> DateWindow | None:
    """Clip a window to the filing dates OpenDART's event reports cover.

    Args:
        window (DateWindow): Requested filing date window.
        today (date): Today in KST.

    Returns:
        DateWindow | None: The window within ``EARLIEST`` to today, or None when it does
            not overlap that range.
    """
    start, end = max(window.start, EARLIEST), min(window.end, today)
    return DateWindow(start, end) if start <= end else None


def tolerate_data_source_errors(error: BaseException) -> bool:
    """Treat ``DataSourceError`` as a failed kind; the default ``tolerate`` policy.

    Args:
        error (BaseException): Failure of one service read.

    Returns:
        bool: True for a ``DataSourceError``.
    """
    return isinstance(error, DataSourceError)


def _split(
    kinds: Sequence[EventKind],
    outcomes: Sequence[tuple[EventRecord, ...] | BaseException],
    tolerate: Callable[[BaseException], bool],
) -> tuple[list[EventRecord], tuple[EventKind, ...]]:
    """Separate answers from tolerated failures, re-raising any other failure.

    Args:
        kinds (Sequence[EventKind]): Kinds queried.
        outcomes (Sequence[tuple[EventRecord, ...] | BaseException]): Results in kind order.
        tolerate (Callable[[BaseException], bool]): Whether a failure marks the kind failed.

    Returns:
        tuple[list[EventRecord], tuple[EventKind, ...]]: Records and kinds that failed.

    Raises:
        BaseException: The first failure, in kind order, that ``tolerate`` rejects.
    """
    records: list[EventRecord] = []
    failed: list[EventKind] = []
    for kind, outcome in zip(kinds, outcomes, strict=True):
        if isinstance(outcome, BaseException) and tolerate(outcome):
            failed.append(kind)
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            records.extend(outcome)
    return records, tuple(failed)


@dataclass(frozen=True, slots=True)
class _Reader:
    """Reads event services for one company and window."""

    corp_code: str
    window: DateWindow
    fetch_service: FetchService
    progress: Progress
    limit: asyncio.Semaphore | None

    async def kind(self, kind: EventKind) -> tuple[EventRecord, ...]:
        """Read one event service.

        Args:
            kind (EventKind): Event kind to read.

        Returns:
            tuple[EventRecord, ...]: Records; empty when the source has none.
        """
        if self.limit is None:
            response = await self.fetch(kind)
        else:
            async with self.limit:
                response = await self.fetch(kind)
        return () if response is None else tuple(records_from(kind, response))

    async def fetch(self, kind: EventKind) -> object | None:
        """Call one event service.

        Args:
            kind (EventKind): Event kind to read.

        Returns:
            object | None: The service's response, or None when the source has none.
        """
        return await self.fetch_service(
            EVENT_KINDS[kind].service,
            volatility="medium",
            corporation_code=self.corp_code,
            filing_start_date=yyyymmdd(self.window.start),
            filing_end_date=yyyymmdd(self.window.end),
        )

    async def kinds(
        self, kinds: Sequence[EventKind], tolerate: Callable[[BaseException], bool]
    ) -> tuple[list[EventRecord], tuple[EventKind, ...]]:
        """Read several event services concurrently, reporting each answer.

        Args:
            kinds (Sequence[EventKind]): Kinds to read.
            tolerate (Callable[[BaseException], bool]): Whether a failure marks a kind failed.

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
            records = await self.kind(kind)
            done += 1
            await self.progress(f"{done}/{len(kinds)} event reports read ({kind})")
            return records

        outcomes = await asyncio.gather(*(one(kind) for kind in kinds), return_exceptions=True)
        return _split(kinds, outcomes, tolerate)


@dataclass(frozen=True, slots=True)
class EventQuery:
    """Which company, window, and event kinds to read.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        window (DateWindow): Original filing date window; see ``covered_window``.
        kinds (tuple[EventKind, ...] | None): Kinds to read; None lets the filing index
            choose (``opendart_analysis.catalog.expand`` turns group names into kinds).
        restrict (frozenset[EventKind] | None): When the index chooses, only these kinds.
        name (str | None): Company name for progress messages; the corp code when None.
    """

    corp_code: str
    window: DateWindow
    kinds: tuple[EventKind, ...] | None = None
    restrict: frozenset[EventKind] | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ReadPolicy:
    """Acquisition limits and partial-result policy for reading events.

    Attributes:
        tolerate (Callable[[BaseException], bool]): Whether a service failure marks its kind
            failed instead of failing the read; by default only ``DataSourceError``.
        concurrency (int | None): Most service calls in flight at once; None leaves the
            bound to the source.
        max_index_pages (int): Most filing-index pages read per disclosure group.
    """

    tolerate: Callable[[BaseException], bool] = tolerate_data_source_errors
    concurrency: int | None = None
    max_index_pages: int = MAX_PAGES


DEFAULT_POLICY: Final = ReadPolicy()
"""Tolerate ``DataSourceError``, leave concurrency to the source, and read 3 index pages."""


async def fetch_events(
    query: EventQuery,
    *,
    fetch_service: FetchService,
    read_filing_page: ReadFilingPage,
    policy: ReadPolicy = DEFAULT_POLICY,
    progress: Progress = no_progress,
) -> EventBatch:
    """Read a company's event reports in a window.

    Event services are read with ``medium`` volatility and the filing index with ``high``.

    Args:
        query (EventQuery): Company, window, and kinds.
        fetch_service (FetchService): Calls a catalog service by SDK method name.
        read_filing_page (ReadFilingPage): Reads one page of the filing index; called only
            when ``query.kinds`` is None.
        policy (ReadPolicy): Failure tolerance, concurrency, and index page limit.
        progress (Progress): Receives progress messages.

    Returns:
        EventBatch: Records newest first, with coverage.
    """
    corp_code, window, kinds = query.corp_code, query.window, query.kinds
    index: EventIndex | None = None
    strategy: Strategy = "requested"
    if kinds is None:
        name = query.name or corp_code
        await progress(f"Searching {name}'s major-issue and offering filings")
        index = await search_index(
            corp_code, window, read_page=read_filing_page, max_pages=policy.max_index_pages
        )
        seen, restrict = index.kinds, query.restrict
        kinds = tuple(k for k in EVENT_KINDS if k in seen and (restrict is None or k in restrict))
        strategy = "filing_index" if index.complete else "all_kinds"
    limit = None if policy.concurrency is None else asyncio.Semaphore(policy.concurrency)
    reader = _Reader(corp_code, window, fetch_service, progress, limit)
    records, failed = await reader.kinds(kinds, policy.tolerate)
    records.sort(key=lambda record: record.filing_number, reverse=True)
    return EventBatch(corp_code, window, strategy, kinds, failed, tuple(records), index)
