"""Resolve requested periods to the fiscal year and report code OpenDART expects.

``latest`` means the most recent periodic report of any kind. The company's filing index
settles it when possible; otherwise candidates come from statutory filing deadlines and
callers probe them in order until one has data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Protocol

from opendart_analysis.domain.filings import clean_title
from opendart_analysis.domain.identifiers import filing_date
from opendart_analysis.domain.periods import (
    FILING_DEADLINE_DAYS,
    FIRST_FISCAL_YEAR,
    filing_deadline,
    latest_candidates,
    parse_periodic_title,
    period_from_title,
)
from opendart_analysis.errors import MissingDataError
from opendart_analysis.upstream import FilingQuery

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from opendart_analysis.domain.periods import PeriodRef, PeriodicTitle
    from opendart_analysis.domain.types import Period
    from opendart_analysis.upstream import FilingRecord, SearchFilings, Volatility

# Annual reports are due 90 days after year end, so 15 months always cover the latest one.
_LOOKBACK = timedelta(days=460)
PROBE_ATTEMPTS = 3
# Reports often arrive on the deadline day and corrections soon after it.
_SETTLING = timedelta(days=14)


class FiscalCompany(Protocol):
    """The company facts that period resolution reads."""

    @property
    def corp_code(self) -> str:
        """8-digit DART corporation code."""
        ...

    @property
    def fye_month(self) -> int:
        """Fiscal year-end month, 1 to 12."""
        ...


class PeriodUnavailableError(MissingDataError):
    """The requested period has not ended yet or predates OpenDART's periodic data.

    Attributes:
        period (Period): Requested period.
        fiscal_year (int | None): Requested fiscal year, if any.
        first_fiscal_year (int): First fiscal year with periodic data.
    """

    def __init__(self, period: Period, fiscal_year: int | None) -> None:
        """Describe the unavailable period.

        Args:
            period (Period): Requested period.
            fiscal_year (int | None): Requested fiscal year, if any.
        """
        wanted = f"{period} {fiscal_year}" if fiscal_year else period
        message = f"No {wanted} period is available: it has not ended yet or predates {FIRST_FISCAL_YEAR}, when OpenDART's periodic data begins."
        super().__init__(message)
        self.period: Period = period
        self.fiscal_year = fiscal_year
        self.first_fiscal_year = FIRST_FISCAL_YEAR


@dataclass(frozen=True, slots=True)
class PeriodicReport:
    """A filed periodic report that defines a period.

    Attributes:
        ref (PeriodRef): Fiscal year and period of the report.
        parsed (PeriodicTitle): Parsed title (kind and period end month).
        filing_number (str): Filing number.
        title (str): Report title as filed, whitespace collapsed.
        filed (date | None): Filing date.
    """

    ref: PeriodRef
    parsed: PeriodicTitle
    filing_number: str
    title: str
    filed: date | None


@dataclass(frozen=True, slots=True)
class ResolvedPeriod:
    """Periods to try for a request, best first.

    Attributes:
        candidates (tuple[PeriodRef, ...]): Periods to probe in order.
        report (PeriodicReport | None): Filing that defined ``latest``, when found.
        note (str | None): Explanation when candidates came from deadlines, not filings.
    """

    candidates: tuple[PeriodRef, ...]
    report: PeriodicReport | None
    note: str | None


def _report(item: FilingRecord, fye_month: int, period: Period) -> PeriodicReport | None:
    """Interpret one search result as a periodic report of the requested period.

    Args:
        item (FilingRecord): Search result.
        fye_month (int): Fiscal year-end month.
        period (Period): Requested period; ``latest`` accepts any.

    Returns:
        PeriodicReport | None: The report, or None when the title does not match.
    """
    parsed = parse_periodic_title(item.report_title or "")
    if parsed is None or item.filing_number is None:
        return None
    refs = [
        r for r in period_from_title(parsed, fye_month=fye_month) if period in {"latest", r.period}
    ]
    if not refs:
        return None
    title = clean_title(item.report_title or "")
    return PeriodicReport(
        refs[0], parsed, item.filing_number, title, filing_date(item.filing_number)
    )


async def latest_periodic_report(
    company: FiscalCompany,
    period: Period = "latest",
    *,
    search_filings: SearchFilings,
    today: date,
) -> PeriodicReport | None:
    """Find the company's most recent final periodic report.

    Reads one page of the company's final periodic reports filed in the last 15 months.

    Args:
        company (FiscalCompany): Company to search.
        period (Period): ``latest`` for any kind, or one period.
        search_filings (SearchFilings): Filing search; asked with ``high`` volatility.
        today (date): Today in KST, which ends the search window.

    Returns:
        PeriodicReport | None: Newest matching report from the last 15 months, if any.
    """
    query = FilingQuery(
        corp_code=company.corp_code,
        start=today - _LOOKBACK,
        end=today,
        group="A",
        final_only=True,
    )
    found = [
        report
        for item in await search_filings(query, volatility="high") or ()
        if (report := _report(item, company.fye_month, period)) is not None
    ]
    # Amended older reports are filed after newer ones, so the newest period wins, not the
    # newest filing; among filings for one period, the latest is the final version.
    return max(found, key=_recency, default=None)


def _recency(report: PeriodicReport) -> tuple[date, date]:
    """Order reports by period end, then filing date.

    Args:
        report (PeriodicReport): Report from the filing index.

    Returns:
        tuple[date, date]: Sort key; unknown dates sort first.
    """
    return (report.ref.end_date or date.min, report.filed or date.min)


async def resolve_period(
    company: FiscalCompany,
    *,
    period: Period,
    fiscal_year: int | None,
    search_filings: SearchFilings,
    today: date,
) -> ResolvedPeriod:
    """Turn a requested period into candidates to probe.

    Without a fiscal year, the newest periodic report in the filing index defines the first
    candidates; the filing search is not called when a fiscal year is given.

    Args:
        company (FiscalCompany): Company the period belongs to.
        period (Period): Requested period.
        fiscal_year (int | None): Requested fiscal year, if any.
        search_filings (SearchFilings): Filing search, used to find the latest report.
        today (date): Today in KST.

    Returns:
        ResolvedPeriod: Candidates, best first.

    Raises:
        PeriodUnavailableError: The requested period has not ended yet or predates 2015.
    """
    fallback = latest_candidates(
        today=today, period=period, fiscal_year=fiscal_year, fye_month=company.fye_month
    )
    report = (
        None
        if fiscal_year is not None
        else await latest_periodic_report(
            company, period, search_filings=search_filings, today=today
        )
    )
    if report is not None:
        # Every label of the report's period comes first (a non-December year end has two);
        # periods ending after it cannot have data yet.
        labels = period_from_title(report.parsed, fye_month=company.fye_month) or (report.ref,)
        end = report.ref.end_date
        rest = tuple(
            ref
            for ref in fallback
            if ref not in labels and (end is None or ref.end_date is None or ref.end_date <= end)
        )
        return ResolvedPeriod((*labels, *rest), report, None)
    if not fallback:
        raise PeriodUnavailableError(period, fiscal_year)
    note = (
        None
        if fiscal_year is not None
        else "No periodic report was found in the last 15 months; periods were chosen by filing deadlines."
    )
    return ResolvedPeriod(fallback, None, note)


async def first_available[R](
    resolved: ResolvedPeriod,
    fetch: Callable[[PeriodRef], Awaitable[R | None]],
    *,
    attempts: int = PROBE_ATTEMPTS,
) -> tuple[PeriodRef, R] | None:
    """Probe candidate periods in order until one has data.

    Args:
        resolved (ResolvedPeriod): Candidates from ``resolve_period``.
        fetch (Callable[[PeriodRef], Awaitable[R | None]]): Fetches one period; None means
            no data.
        attempts (int): Maximum candidates to try.

    Returns:
        tuple[PeriodRef, R] | None: First period with data and its data, or None.
    """
    for ref in resolved.candidates[:attempts]:
        result = await fetch(ref)
        if result is not None:
            return ref, result
    return None


def period_volatility(ref: PeriodRef, *, fye_month: int, today: date) -> Volatility:
    """Say how quickly a period's periodic-report or statement data can still change.

    Until a period's filing deadline (plus two weeks for late filers and corrections) has
    passed, its data may still appear or change, so it is ``high``; afterwards it is ``low``.
    The deadline counts from the period's known end date, since a start-year label of a
    non-December fiscal year would otherwise place it a year early.

    Args:
        ref (PeriodRef): Period being fetched.
        fye_month (int): Fiscal year-end month, which sets the deadline without an end date.
        today (date): Today in KST.

    Returns:
        Volatility: ``high`` inside the filing window, else ``low``.
    """
    if ref.end_date is not None:
        deadline = ref.end_date + timedelta(days=FILING_DEADLINE_DAYS[ref.period])
    else:
        deadline = filing_deadline(ref.fiscal_year, ref.period, fye_month=fye_month)
    return "high" if today <= deadline + _SETTLING else "low"
