"""Find the newest period with data, then chain earlier reports for multi-year tables.

Earlier reports are fetched concurrently with the basis the newest report used, so columns
never mix consolidated and separate figures. Acquisition is bounded: at most
``PROBE_ATTEMPTS`` candidate periods are probed, then at most ``MAX_REPORTS - 1`` earlier
reports are fetched, none before the first fiscal year with data.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

import anyio

from opendart_analysis.domain.periods import FIRST_FISCAL_YEAR, fiscal_years_back
from opendart_analysis.reports import first_available

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Basis
    from opendart_analysis.financials.statements import Report
    from opendart_analysis.reports import ResolvedPeriod

    type FetchReport = Callable[[PeriodRef, Basis], Awaitable[Report | None]]

type Progress = Callable[[str], Awaitable[None]]
"""Async callback that receives short progress messages, such as "2/3 Fetching FY2022"."""

ANNUAL_STEP: Final = 3
"""Fiscal years between chained annual reports, each of which covers three years."""

MAX_REPORTS: Final = 10
"""Most reports one request chains, the newest included."""


async def no_progress(message: str) -> None:
    """Discard a progress message.

    Args:
        message (str): Ignored.
    """
    del message


def check_reports(years: int) -> None:
    """Reject a report count outside the acquisition bound.

    Args:
        years (int): Reports wanted, newest first.

    Raises:
        ValueError: ``years`` is outside 1 to ``MAX_REPORTS``.
    """
    if not 1 <= years <= MAX_REPORTS:
        message = f"years must be between 1 and {MAX_REPORTS}; got {years}."
        raise ValueError(message)


async def gather[T](calls: Sequence[Callable[[], Awaitable[T]]]) -> list[T]:
    """Await calls concurrently and return their results in call order.

    Every call runs to completion. A failure is raised as it was, never wrapped in an
    exception group, once all calls have finished; when several fail, the first to fail wins.
    Cancellation is not intercepted.

    Args:
        calls (Sequence[Callable[[], Awaitable[T]]]): Zero-argument coroutine functions.

    Returns:
        list[T]: One result per call, in order.
    """
    results: dict[int, T] = {}
    errors: list[Exception] = []

    async def run(index: int, call: Callable[[], Awaitable[T]]) -> None:
        """Run one call and collect its failure for propagation afterward.

        Args:
            index (int): Position used to restore the input order.
            call (Callable[[], Awaitable[T]]): Zero-argument coroutine function to await.
        """
        try:
            results[index] = await call()
        except Exception as error:  # noqa: BLE001 - re-raised unchanged after the group ends.
            errors.append(error)

    async with anyio.create_task_group() as group:
        for index, call in enumerate(calls):
            group.start_soon(run, index, call)
    if errors:
        raise errors[0]
    return [results[index] for index in range(len(calls))]


@dataclass(frozen=True, slots=True)
class Span:
    """How far back to chain reports.

    Attributes:
        years (int): Reports to return, newest first.
        step (int | None): Fiscal years between chained reports; None chains annual reports
            three years apart (each covers three years) and other reports one year apart.
        earliest (int): First fiscal year with data for this kind of report.
    """

    years: int = 1
    step: int | None = None
    earliest: int = FIRST_FISCAL_YEAR


@dataclass(frozen=True, slots=True)
class Chain:
    """The newest period with data and the reports chained from it.

    Attributes:
        ref (PeriodRef): Newest period with data.
        reports (tuple[Report, ...]): Reports found, newest first.
        notes (tuple[str, ...]): Period fallbacks and missing years.
    """

    ref: PeriodRef
    reports: tuple[Report, ...]
    notes: tuple[str, ...]


def fallback_note(candidates: Sequence[PeriodRef], ref: PeriodRef) -> str | None:
    """Explain when the newest candidate period had no data.

    Args:
        candidates (Sequence[PeriodRef]): Periods probed, best first.
        ref (PeriodRef): Period that had data.

    Returns:
        str | None: Note, or None when the first candidate had data.
    """
    if not candidates or candidates[0] == ref:
        return None
    return f"OpenDART has no data for {candidates[0].label} yet; showing {ref.label}."


def _missing_notes(earlier: Sequence[PeriodRef], older: Sequence[Report | None]) -> list[str]:
    """Name earlier periods that returned no data.

    Args:
        earlier (Sequence[PeriodRef]): Earlier periods requested.
        older (Sequence[Report | None]): Fetched reports, aligned with ``earlier``.

    Returns:
        list[str]: One note, or none when every period had data.
    """
    missing = [
        period.label for period, report in zip(earlier, older, strict=True) if report is None
    ]
    return [f"No data for {", ".join(missing)}; earlier columns are missing."] if missing else []


async def chain(
    resolved: ResolvedPeriod,
    fetch: FetchReport,
    *,
    basis: Basis,
    span: Span,
    progress: Progress,
) -> Chain | None:
    """Find the newest period with data, then fetch earlier reports for more years.

    Args:
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        fetch (FetchReport): Fetches one period's report with a basis; None means no data.
        basis (Basis): Requested basis; chained reports use the basis the newest one used.
        span (Span): Reports wanted (validated by the caller with ``check_reports``), the
            fiscal years between them, and the first year.
        progress (Progress): Receives one message per report fetched.

    Returns:
        Chain | None: Reports and notes, or None when no candidate period has data.
    """
    candidates = tuple(ref for ref in resolved.candidates if ref.fiscal_year >= span.earliest)

    async def probe(ref: PeriodRef) -> Report | None:
        """Fetch one candidate period while reporting its progress.

        Args:
            ref (PeriodRef): Candidate period to fetch.

        Returns:
            Report | None: Fetched report, or None when the period has no data.
        """
        await progress(f"Fetching {ref.label}")
        return await fetch(ref, basis)

    found = await first_available(replace(resolved, candidates=candidates), probe)
    if found is None:
        return None
    ref, newest = found
    notes = [note for note in (resolved.note, fallback_note(candidates, ref)) if note]
    step = span.step or (ANNUAL_STEP if ref.period == "FY" else 1)
    back = fiscal_years_back(ref, span.years, step=step)[1:]
    earlier = [period for period in back if period.fiscal_year >= span.earliest]
    follow = newest.basis or basis

    def bind(index: int, period: PeriodRef) -> Callable[[], Awaitable[Report | None]]:
        """Bind one earlier period to its progress message and selected basis.

        Args:
            index (int): One-based column position in the chained table.
            period (PeriodRef): Earlier period to fetch.

        Returns:
            Callable[[], Awaitable[Report | None]]: Deferred fetch for this period.
        """

        async def call() -> Report | None:
            """Fetch the bound earlier report and report its progress.

            Returns:
                Report | None: Fetched report, or None when the period has no data.
            """
            await progress(f"{index}/{len(earlier) + 1} Fetching {period.label}")
            return await fetch(period, follow)

        return call

    older = await gather([bind(index, period) for index, period in enumerate(earlier, 2)])
    notes.extend(_missing_notes(earlier, older))
    return Chain(ref, (newest, *(r for r in older if r is not None)), tuple(notes))
