"""Fetch periodic-report extracts, run fetches together, and describe where records came from.

Thirty OpenDART services return tables from periodic reports, keyed by corporation code, fiscal
year, and report code. Each fetch goes through a caller-supplied ``FetchService`` with the
period's volatility, following ``opendart_analysis.upstream``.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import takewhile
from typing import TYPE_CHECKING, Final

import anyio

from opendart_analysis.domain.identifiers import is_filing_number
from opendart_analysis.extracts.fields import records
from opendart_analysis.reports import PROBE_ATTEMPTS, period_volatility

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable
    from datetime import date

    from opendart_analysis.reports import FiscalCompany, PeriodRef, PeriodicReport, ResolvedPeriod
    from opendart_analysis.upstream import FetchService

PERIODIC_PARAMS: Final = ("corporation_code", "fiscal_year", "report_period")
"""Request parameters, by SDK name, that every periodic-report service takes."""


@dataclass(frozen=True, slots=True)
class FilingSource:
    """A filing that records came from.

    Attributes:
        filing_number (str): 14-digit filing (receipt) number.
        title (str | None): Report title as filed, when known.
    """

    filing_number: str
    title: str | None = None


async def fetch_response(
    service: str,
    *,
    company: FiscalCompany,
    ref: PeriodRef,
    fetch_service: FetchService,
    today: date,
) -> object | None:
    """Call one periodic-report service for a company and period.

    The call is ``high`` volatility while the period's filing window is open, so a report
    filed or corrected meanwhile can be picked up, and ``low`` once it has settled (see
    ``opendart_analysis.reports.period_volatility``).

    Args:
        service (str): SDK method name, such as ``alot_matter``.
        company (FiscalCompany): Company; its fiscal year-end month sets the filing deadline.
        ref (PeriodRef): Fiscal year and period.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        object | None: The response, or None when the source has no data.
    """
    return await fetch_service(
        service,
        volatility=period_volatility(ref, fye_month=company.fye_month, today=today),
        corporation_code=company.corp_code,
        fiscal_year=str(ref.fiscal_year),
        report_period=ref.report_code,
    )


async def fetch_records(
    service: str,
    *,
    company: FiscalCompany,
    ref: PeriodRef,
    fetch_service: FetchService,
    today: date,
) -> list[object] | None:
    """Fetch one periodic-report service's ``list`` records for a company and period.

    Args:
        service (str): SDK method name.
        company (FiscalCompany): Company.
        ref (PeriodRef): Fiscal year and period.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        list[object] | None: Records, or None when the source has no data.
    """
    response = await fetch_response(
        service, company=company, ref=ref, fetch_service=fetch_service, today=today
    )
    return None if response is None else records(response)


async def gather_all[T](calls: Iterable[Awaitable[T]]) -> list[T]:
    """Await calls concurrently and return their results in order.

    Every call runs to completion, so a caching source keeps each answer; then the first
    failure in call order, if any, is raised unwrapped, never inside an exception group. That
    keeps an ``AnalysisError`` or an exception from the caller's data access recognizable.

    Args:
        calls (Iterable[Awaitable[T]]): Calls to await.

    Returns:
        list[T]: Results in call order.

    Raises:
        Exception: The first failure among the calls, in call order.
    """
    pending = list(calls)
    results: dict[int, T] = {}
    failures: dict[int, Exception] = {}

    async def run(index: int, call: Awaitable[T]) -> None:
        """Await one call and keep its result or failure.

        Args:
            index (int): Position of the call, which restores the input order.
            call (Awaitable[T]): Call to await.
        """
        try:
            results[index] = await call
        except Exception as error:  # noqa: BLE001 - raised again below, unwrapped
            failures[index] = error

    async with anyio.create_task_group() as group:
        for index, call in enumerate(pending):
            group.start_soon(run, index, call)
    if failures:
        raise failures[min(failures)]
    return [results[index] for index in range(len(pending))]


def probe_attempts(resolved: ResolvedPeriod) -> int:
    """Choose how many candidate periods to probe for data.

    A periodic report found in the filing index settles the period, so only that period is
    read, under each fiscal-year label it may have: with a non-December year end, OpenDART
    may label the year by the year it ends or the year it starts, and ``resolve_period``
    lists the second label right after the report's. Periods guessed from filing deadlines
    are probed up to ``PROBE_ATTEMPTS``.

    Args:
        resolved (ResolvedPeriod): Candidates from ``resolve_period``.

    Returns:
        int: The number of leading candidates for the filed report's period, one per
            fiscal-year label, or ``PROBE_ATTEMPTS`` without a report.
    """
    report = resolved.report
    if report is None:
        return PROBE_ATTEMPTS
    end = report.ref.end_date
    labels = takewhile(
        lambda ref: ref.period == report.ref.period and end is not None and ref.end_date == end,
        resolved.candidates,
    )
    return min(max(sum(1 for _ in labels), 1), PROBE_ATTEMPTS)


def checked(resolved: ResolvedPeriod) -> str:
    """Name the report, or the periods probed, for notes that report missing data.

    Args:
        resolved (ResolvedPeriod): Candidates from ``resolve_period``.

    Returns:
        str: The report title in quotes, or period labels such as "FY2025, FY2024".
    """
    if resolved.report is not None:
        return f'"{resolved.report.title}"'
    return ", ".join(ref.label for ref in resolved.candidates[: probe_attempts(resolved)])


def sources(
    numbers: Iterable[str | None], report: PeriodicReport | None = None
) -> list[FilingSource]:
    """Describe the filings that records came from, in order of first appearance.

    Args:
        numbers (Iterable[str | None]): Filing numbers from records; invalid ones are skipped.
        report (PeriodicReport | None): Report found in the filing index, for its title.

    Returns:
        list[FilingSource]: One entry per distinct filing number.
    """
    unique = dict.fromkeys(n.strip() for n in numbers if n and is_filing_number(n.strip()))
    return [
        FilingSource(n, report.title if report and report.filing_number == n else None)
        for n in unique
    ]
