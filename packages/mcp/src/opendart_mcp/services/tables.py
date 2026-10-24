"""Shared plumbing for get_financials views: period probing, report chains, and tables.

A view probes the candidate periods for the newest one with data, then chains earlier
reports for multi-year tables, fetching them concurrently with the basis the newest report
used, so columns never mix consolidated and separate figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.identifiers import is_filing_number
from opendart_analysis.domain.periods import FIRST_FISCAL_YEAR, fiscal_years_back
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.services.fanout import gather
from opendart_mcp.services.periods import first_available

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Basis
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.models.financials import (
        EquityInvestment,
        PeriodColumn,
        StatementBasis,
        StatementRow,
    )
    from opendart_mcp.services.periods import PeriodicReport, ResolvedPeriod
    from opendart_mcp.services.statements import Report

    type Fetch = Callable[[PeriodRef, Basis], Awaitable[Report | None]]

ANNUAL_STEP: Final = 3
"""Fiscal years between chained annual reports, each of which covers three years."""


@dataclass(slots=True)
class Table:
    """What a view returns: the table and its provenance.

    Attributes:
        periods (list[PeriodColumn]): Columns, latest first.
        rows (list[StatementRow]): Rows aligned with the columns.
        notes (list[str]): Fallbacks, coverage gaps, and formulas.
        filings (list[SourceFiling]): Filings the table comes from.
        basis (StatementBasis | None): Statements used, where a basis applies.
        currency (str): Currency of the amounts.
        derived (dict[str, float]): Metrics computed in code.
        investments (list[EquityInvestment] | None): Holdings (equity_investments view).
    """

    periods: list[PeriodColumn] = field(default_factory=list)
    rows: list[StatementRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    filings: list[SourceFiling] = field(default_factory=list)
    basis: StatementBasis | None = None
    currency: str = "KRW"
    derived: dict[str, float] = field(default_factory=dict)
    investments: list[EquityInvestment] | None = None


@dataclass(frozen=True, slots=True)
class Span:
    """How far back a view chains reports.

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
        reports (list[Report]): Reports found, newest first.
        notes (list[str]): Period fallbacks and missing years.
    """

    ref: PeriodRef
    reports: list[Report]
    notes: list[str]


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
    fetch: Fetch,
    *,
    basis: Basis,
    span: Span,
    progress: Progress,
) -> Chain | None:
    """Find the newest period with data, then fetch earlier reports for more years.

    Args:
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        fetch (Fetch): Fetches one period's report with a basis; None means no data.
        basis (Basis): Requested basis; chained reports use the basis the newest one used.
        span (Span): Reports wanted, the fiscal years between them, and the first year.
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

        Raises:
            ServerError: Progress reporting or the upstream fetch fails.
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

            Raises:
                ServerError: Progress reporting or the upstream fetch fails.
            """
            await progress(f"{index}/{len(earlier) + 1} Fetching {period.label}")
            return await fetch(period, follow)

        return call

    older = await gather([bind(index, period) for index, period in enumerate(earlier, 2)])
    notes.extend(_missing_notes(earlier, older))
    return Chain(ref, [newest, *(report for report in older if report is not None)], notes)


def sources(filings: Iterable[str], report: PeriodicReport | None) -> list[SourceFiling]:
    """Cite filings, titling the one that defined the requested period.

    Malformed filing numbers are skipped rather than failing the whole result.

    Args:
        filings (Iterable[str]): Filing numbers.
        report (PeriodicReport | None): Periodic report found in the filing index.

    Returns:
        list[SourceFiling]: Provenance entries.
    """
    titles = {report.filing_number: report.title} if report is not None else {}
    numbers = (number.strip() for number in filings)
    return [
        SourceFiling.of(number, titles.get(number))
        for number in dict.fromkeys(numbers)
        if is_filing_number(number)
    ]


def no_data(resolved: ResolvedPeriod, what: str) -> str:
    """Explain an empty result.

    Args:
        resolved (ResolvedPeriod): Candidate periods that were probed.
        what (str): What was looked for, such as "financial statements".

    Returns:
        str: Note naming the periods tried.
    """
    tried = ", ".join(ref.label for ref in resolved.candidates[:3]) or "the requested period"
    return f"OpenDART has no {what} for {tried}: the report may not be filed yet, or the company is not covered (financial companies and small filers often lack XBRL data)."
