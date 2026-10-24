"""Assemble a corporate-action calendar for one company or a watchlist.

Each company's event reports are read as ``Reads`` plans, and its debt maturities, when a
reader is given, at the same time. Event dates become items (``event_items``), dates that a
registration statement repeats from its decision are merged, and debt maturities replace the
event maturities of the same bond (``merge_maturities``). Companies are read concurrently;
a company whose read fails with an exception the policy tolerates is reported with that
error and no items, and any other failure propagates once every company has finished.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from opendart_analysis.calendar.items import event_items, merge_maturities, sort_key
from opendart_analysis.calendar.lookback import Reads
from opendart_analysis.calendar.reads import read_events
from opendart_analysis.calendar.request import MAX_COMPANIES, TooManyCompaniesError
from opendart_analysis.events import DEFAULT_POLICY
from opendart_analysis.upstream import no_progress

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import date

    from opendart_analysis.calendar.items import CalendarItem
    from opendart_analysis.calendar.request import CalendarSubject
    from opendart_analysis.catalog import EventKind
    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.events import EventBatch, ReadPolicy
    from opendart_analysis.filings import ReadFilingPage
    from opendart_analysis.upstream import FetchService, Progress


class MaturityAnswer(Protocol):
    """What a maturity reader returns: calendar items, and anything else it reports."""

    @property
    def items(self) -> Sequence[CalendarItem]:
        """Debt maturity items; those outside the calendar window are dropped."""
        ...


type ReadMaturities[M: MaturityAnswer] = Callable[[CalendarSubject, DateWindow], Awaitable[M]]
"""Debt maturity source: (company, calendar window) to an answer with items, such as
``read_debt_maturities``."""


@dataclass(frozen=True, slots=True)
class CompanyCalendar[M: MaturityAnswer]:
    """One company's part of a calendar.

    Attributes:
        subject (CalendarSubject): Company.
        items (tuple[CalendarItem, ...]): Its items within the window, unsorted: event
            items, then debt maturities.
        events (tuple[EventBatch, ...]): Event batches read, recent window first.
        failed (tuple[EventKind, ...]): Event kinds whose service failed with a tolerated
            error, in the order read.
        maturities (M | None): The maturity reader's answer, or None when none was read.
        error (Exception | None): Tolerated failure that left the company without items.
    """

    subject: CalendarSubject
    items: tuple[CalendarItem, ...] = ()
    events: tuple[EventBatch, ...] = ()
    failed: tuple[EventKind, ...] = ()
    maturities: M | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class CorporateActionCalendar[M: MaturityAnswer]:
    """Corporate-action dates for one company or a watchlist.

    Attributes:
        window (DateWindow): Calendar dates covered.
        reads (Reads): Event reports read, and from when.
        companies (tuple[CompanyCalendar[M], ...]): One entry per distinct company, in
            input order.
        items (tuple[CalendarItem, ...]): Every company's items, sorted by date, company
            name, action (``ACTION_ORDER``), and filing number.
    """

    window: DateWindow
    reads: Reads
    companies: tuple[CompanyCalendar[M], ...]
    items: tuple[CalendarItem, ...]


@dataclass(frozen=True, slots=True)
class _Reader[M: MaturityAnswer]:
    """Reads one company's calendar inputs."""

    window: DateWindow
    reads: Reads
    maturities: ReadMaturities[M] | None
    fetch_service: FetchService
    read_filing_page: ReadFilingPage
    policy: ReadPolicy

    async def debt(self, subject: CalendarSubject) -> M | None:
        """Ask the maturity reader for one company's debt maturities.

        Args:
            subject (CalendarSubject): Company.

        Returns:
            M | None: The answer, or None without a reader.
        """
        return None if self.maturities is None else await self.maturities(subject, self.window)

    async def company(self, subject: CalendarSubject) -> CompanyCalendar[M]:
        """Collect one company's items, reading events and debt concurrently.

        Args:
            subject (CalendarSubject): Company.

        Returns:
            CompanyCalendar[M]: Items and coverage.

        Raises:
            BaseException: The first failure of either read, after both have finished.
        """
        batches, answer = await asyncio.gather(
            read_events(
                subject.corp_code,
                self.reads,
                fetch_service=self.fetch_service,
                read_filing_page=self.read_filing_page,
                policy=self.policy,
            ),
            self.debt(subject),
            return_exceptions=True,
        )
        if isinstance(batches, BaseException):
            raise batches
        if isinstance(answer, BaseException):
            raise answer
        span = self.window
        records = [record for batch in batches for record in batch.records]
        debt = () if answer is None else answer.items
        due = [item for item in debt if span.start <= item.date <= span.end]
        items = merge_maturities(event_items(subject.corp_code, records, span), due)
        failed = tuple(kind for batch in batches for kind in batch.failed)
        return CompanyCalendar(subject, tuple(items), tuple(batches), failed, answer)

    async def companies(
        self, subjects: Sequence[CalendarSubject], progress: Progress
    ) -> list[CompanyCalendar[M]]:
        """Collect every company's items concurrently, reporting each company.

        Args:
            subjects (Sequence[CalendarSubject]): Distinct companies.
            progress (Progress): Receives "7/20 Samsung Electronics" messages.

        Returns:
            list[CompanyCalendar[M]]: One entry per company, in input order.

        Raises:
            BaseException: The first failure, in company order, that the policy rejects.
        """
        done = 0

        async def one(subject: CalendarSubject) -> CompanyCalendar[M]:
            """Collect one company's calendar and report its completion.

            Args:
                subject (CalendarSubject): Company.

            Returns:
                CompanyCalendar[M]: The company's items and coverage.
            """
            nonlocal done
            found = await self.company(subject)
            done += 1
            await progress(f"{done}/{len(subjects)} {subject.name}")
            return found

        outcomes = await asyncio.gather(*(one(s) for s in subjects), return_exceptions=True)
        companies: list[CompanyCalendar[M]] = []
        for subject, outcome in zip(subjects, outcomes, strict=True):
            if isinstance(outcome, Exception) and self.policy.tolerate(outcome):
                companies.append(CompanyCalendar(subject, error=outcome))
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                companies.append(outcome)
        return companies


def _distinct(subjects: Sequence[CalendarSubject], limit: int) -> list[CalendarSubject]:
    """Keep the first subject of each corporation code, within the bound.

    Args:
        subjects (Sequence[CalendarSubject]): Companies as given.
        limit (int): Most distinct companies.

    Returns:
        list[CalendarSubject]: Distinct companies in input order.

    Raises:
        TooManyCompaniesError: More distinct companies than ``limit``.
    """
    distinct: dict[str, CalendarSubject] = {}
    for subject in subjects:
        distinct.setdefault(subject.corp_code, subject)
    unique = list(distinct.values())
    if len(unique) > limit:
        raise TooManyCompaniesError(count=len(unique), limit=limit)
    return unique


async def corporate_action_calendar[M: MaturityAnswer](  # noqa: PLR0913 - explicit data access, limits, clock, and progress
    subjects: Sequence[CalendarSubject],
    *,
    window: DateWindow,
    kinds: tuple[EventKind, ...] | None = None,
    maturities: ReadMaturities[M] | None = None,
    fetch_service: FetchService,
    read_filing_page: ReadFilingPage,
    policy: ReadPolicy = DEFAULT_POLICY,
    max_companies: int = MAX_COMPANIES,
    today: date,
    progress: Progress = no_progress,
) -> CorporateActionCalendar[M]:
    """Collect corporate-action dates for companies within a window.

    Args:
        subjects (Sequence[CalendarSubject]): Companies; repeated corporation codes are read
            once.
        window (DateWindow): Calendar dates, such as from ``calendar_window``.
        kinds (tuple[EventKind, ...] | None): Event kinds to read, such as
            ``calendar_kinds(...).events``; None lets each company's filing index choose;
            empty reads no event reports.
        maturities (ReadMaturities[M] | None): Debt maturity reader, such as
            ``read_debt_maturities(...)``; None reads none.
        fetch_service (FetchService): Calls event services.
        read_filing_page (ReadFilingPage): Reads each company's filing index when ``kinds``
            is None.
        policy (ReadPolicy): Failures that mark an event kind failed, and a company failed
            when they escape its reads; concurrency; and index page limit.
        max_companies (int): Most distinct companies.
        today (date): Today in KST; filings are read up to it.
        progress (Progress): Receives "7/20 Samsung Electronics" as each company finishes.

    Returns:
        CorporateActionCalendar[M]: Items sorted by date, with each company's coverage.

    Raises:
        TooManyCompaniesError: More distinct companies than ``max_companies``.
    """
    unique = _distinct(subjects, max_companies)
    reads = Reads.before(window.start, today=today, kinds=kinds)
    reader = _Reader(window, reads, maturities, fetch_service, read_filing_page, policy)
    companies = await reader.companies(unique, progress)
    names = {subject.corp_code: subject.name for subject in unique}
    found = [item for company in companies for item in company.items]
    found.sort(key=lambda item: sort_key(item, names.get(item.corp_code, "")))
    return CorporateActionCalendar(window, reads, tuple(companies), tuple(found))
