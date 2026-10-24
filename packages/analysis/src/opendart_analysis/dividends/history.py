"""Read a company's dividend history from its annual reports.

The newest annual report with a dividend table covers three fiscal years; longer histories
chain earlier annual reports, one call per three fiscal years, fetched concurrently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.dividends.rows import merge
from opendart_analysis.domain.periods import fiscal_years_back
from opendart_analysis.extracts import fetch_records, gather_all, probe_attempts, sources, text
from opendart_analysis.reports import first_available

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from opendart_analysis.dividends.rows import Batch, DividendRow
    from opendart_analysis.extracts import FilingSource
    from opendart_analysis.reports import FiscalCompany, PeriodRef, ResolvedPeriod
    from opendart_analysis.upstream import FetchService

SERVICE: Final = "alot_matter"
"""SDK method name of the dividend table (``periodic_reports.alot_matter``)."""

YEARS_PER_REPORT: Final = 3
"""Fiscal years one annual report's dividend table covers."""

MAX_YEARS: Final = 10
"""Most fiscal years one history covers, at most four annual reports."""

YIELD_NOTE: Final = "Yields are as filed, computed by the company from its own reference price; OpenDART has no market prices, so they are not recomputed."
"""Note added when a history has yields."""

_YIELDS: Final = frozenset({"cash_yield", "stock_yield"})


@dataclass(frozen=True, slots=True)
class DividendHistory:
    """A company's dividends by measure, share class, and fiscal year.

    Attributes:
        ref (PeriodRef): Newest annual report period with a dividend table.
        rows (tuple[DividendRow, ...]): Every merged row, dividends first, including par value
            and rows without values.
        fiscal_years (tuple[int, ...]): Fiscal years with any value, newest first.
        sources (tuple[FilingSource, ...]): Filings the rows came from, newest report first.
        missing (tuple[PeriodRef, ...]): Earlier annual reports without a dividend table.
        notes (tuple[str, ...]): Missing earlier reports, then how yields were computed.
    """

    ref: PeriodRef
    rows: tuple[DividendRow, ...]
    fiscal_years: tuple[int, ...]
    sources: tuple[FilingSource, ...]
    missing: tuple[PeriodRef, ...]
    notes: tuple[str, ...]


def _notes(rows: Sequence[DividendRow], missing: Sequence[PeriodRef]) -> tuple[str, ...]:
    """Explain gaps and how yields were computed.

    Args:
        rows (Sequence[DividendRow]): Merged rows.
        missing (Sequence[PeriodRef]): Annual reports without dividend data.

    Returns:
        tuple[str, ...]: Notes.
    """
    notes = []
    if missing:
        labels = ", ".join(ref.label for ref in missing)
        notes.append(f"No dividend table for {labels}; earlier years are missing.")
    if any(row.measure in _YIELDS and row.values for row in rows):
        notes.append(YIELD_NOTE)
    return tuple(notes)


async def _earlier(
    company: FiscalCompany,
    newest: Batch,
    *,
    years: int,
    fetch_service: FetchService,
    today: date,
) -> tuple[list[Batch], list[PeriodRef]]:
    """Fetch the earlier annual reports a history needs.

    Args:
        company (FiscalCompany): Company.
        newest (Batch): Newest annual report with data.
        years (int): Fiscal years requested.
        fetch_service (FetchService): Service calls.
        today (date): Today in KST.

    Returns:
        tuple[list[Batch], list[PeriodRef]]: Reports with data, newest first, and the
            periods that had none.
    """
    calls = math.ceil(years / YEARS_PER_REPORT)
    refs = fiscal_years_back(newest[0], calls, step=YEARS_PER_REPORT)[1:]
    found = await gather_all(
        fetch_records(SERVICE, company=company, ref=ref, fetch_service=fetch_service, today=today)
        for ref in refs
    )
    batches = [newest, *((r, rows) for r, rows in zip(refs, found, strict=True) if rows)]
    return batches, [r for r, rows in zip(refs, found, strict=True) if rows is None]


async def dividend_history(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    years: int = YEARS_PER_REPORT,
    fetch_service: FetchService,
    today: date,
) -> DividendHistory | None:
    """Build a company's dividend history from its annual reports.

    Probes the candidate annual periods for a dividend table (one per fiscal-year label of a
    filed report, else up to three), then fetches ``ceil(years / 3) - 1`` earlier annual
    reports concurrently; earlier fiscal years stop at 2015.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Annual candidates from ``resolve_period(period="FY")``.
        years (int): Fiscal years of history, newest first, 1 to ``MAX_YEARS``.
        fetch_service (FetchService): Service calls, asked for ``alot_matter`` with the
            period's volatility; failures propagate unchanged, the first in call order.
        today (date): Today in KST, which sets each period's volatility.

    Returns:
        DividendHistory | None: The history, or None when no candidate has a dividend table.

    Raises:
        ValueError: ``years`` is outside 1 to ``MAX_YEARS``, or a candidate is not annual.
    """
    if not 1 <= years <= MAX_YEARS:
        message = f"years must be between 1 and {MAX_YEARS}; got {years}."
        raise ValueError(message)
    if any(ref.period != "FY" for ref in resolved.candidates):
        message = 'Dividend histories read annual reports; resolve the period with period="FY".'
        raise ValueError(message)
    found = await first_available(
        resolved,
        lambda ref: fetch_records(
            SERVICE, company=company, ref=ref, fetch_service=fetch_service, today=today
        ),
        attempts=probe_attempts(resolved),
    )
    if found is None:
        return None
    batches, missing = await _earlier(
        company, found, years=years, fetch_service=fetch_service, today=today
    )
    newest = found[0].fiscal_year
    rows = merge(batches, range(newest - years + 1, newest + 1))
    numbers = (text(record, "filing_number") for _, records in batches for record in records)
    return DividendHistory(
        ref=found[0],
        rows=rows,
        fiscal_years=tuple(sorted({year for row in rows for year in row.values}, reverse=True)),
        sources=tuple(sources(numbers, resolved.report)),
        missing=tuple(missing),
        notes=_notes(rows, missing),
    )
