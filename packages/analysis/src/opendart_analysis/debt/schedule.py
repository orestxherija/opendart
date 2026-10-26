"""Debt maturities in a date window, with the corporate-bond ladder, from periodic reports.

Issuance records list only securities issued in the period, so ``maturity_schedule`` reads the
latest report's record and, for a quarterly or half-year report, the previous annual report's
record, covering issues of the current and prior fiscal years. The latest corporate-bond
ladder covers every bond outstanding at the period end, so it is the complete view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_analysis.debt.issuance import ISSUANCE_SERVICE, company_names, maturities
from opendart_analysis.debt.ladders import BONDS, build_ladder
from opendart_analysis.domain.periods import FIRST_FISCAL_YEAR, PeriodRef
from opendart_analysis.extracts import fetch_records, gather_all, probe_attempts
from opendart_analysis.reports import first_available

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from opendart_analysis.debt.issuance import Maturity
    from opendart_analysis.debt.ladders import Ladder
    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.reports import FiscalCompany, ResolvedPeriod
    from opendart_analysis.upstream import FetchService

type _Tables = tuple[list[object] | None, list[object] | None, list[object] | None]
"""A period's issuance rows and corporate-bond balance rows, and prior annual issuance rows."""


@dataclass(frozen=True, slots=True)
class MaturitySchedule:
    """Debt maturities in a window, with the report they come from.

    Attributes:
        maturities (tuple[Maturity, ...]): Maturities by date, each issue once.
        period (PeriodRef | None): Latest period read, or None when no report had debt
            tables.
        bonds (Ladder | None): Corporate bonds outstanding at that period's end by remaining
            maturity, or None when none are reported.
    """

    maturities: tuple[Maturity, ...] = ()
    period: PeriodRef | None = None
    bonds: Ladder | None = None


def prior_annual(ref: PeriodRef) -> PeriodRef | None:
    """Name the annual report before a quarterly or half-year period.

    Args:
        ref (PeriodRef): Latest period.

    Returns:
        PeriodRef | None: The previous fiscal year, or None for annual or first-year periods.
    """
    if ref.period == "FY" or ref.fiscal_year <= FIRST_FISCAL_YEAR:
        return None
    return PeriodRef(ref.fiscal_year - 1, "FY")


async def _schedule_tables(
    company: FiscalCompany, ref: PeriodRef, *, fetch_service: FetchService, today: date
) -> _Tables:
    """Fetch a period's issuance record and bond balances, and the prior annual record.

    Args:
        company (FiscalCompany): Company.
        ref (PeriodRef): Candidate latest period.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        _Tables: Issuance rows, corporate-bond balance rows, and the prior annual report's
            issuance rows when the period is not annual; None where the source has no data.
    """
    refs = [(ISSUANCE_SERVICE, ref), (BONDS.service, ref)]
    if (prior := prior_annual(ref)) is not None:
        refs.append((ISSUANCE_SERVICE, prior))
    issues, balances, *earlier = await gather_all(
        fetch_records(name, company=company, ref=period, fetch_service=fetch_service, today=today)
        for name, period in refs
    )
    return issues, balances, earlier[0] if earlier else None


async def _latest_tables(
    company: FiscalCompany, ref: PeriodRef, *, fetch_service: FetchService, today: date
) -> _Tables | None:
    """Fetch a candidate latest period's tables, for probing.

    Args:
        company (FiscalCompany): Company.
        ref (PeriodRef): Candidate latest period.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        _Tables | None: The tables, or None when the period itself has neither an issuance
            record nor bond balances, whatever the prior annual record holds.
    """
    tables = await _schedule_tables(company, ref, fetch_service=fetch_service, today=today)
    return None if tables[0] is None and tables[1] is None else tables


async def maturity_schedule(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    window: DateWindow,
    names: Iterable[str | None],
    fetch_service: FetchService,
    today: date,
) -> MaturitySchedule:
    """List debt securities that mature in a window, with the corporate-bond ladder.

    Reads the issuance record and the corporate-bond balance of the first candidate period
    that has either and, when that period is a quarterly or half-year one, the issuance
    record of the previous annual report. Older issues appear only when the company lists
    them again, so the ladder is the complete view. Candidates are probed like
    ``debt_profile``; when none has tables of its own, the annual report before the first
    candidate is read as the latest. Fully redeemed issues are skipped; partly redeemed ones
    keep their original face value with their status. Costs two or three calls per period
    probed, and two more for the fallback.

    Args:
        company (FiscalCompany): Company.
        resolved (ResolvedPeriod): Candidates for the latest period, from
            ``resolve_period(company, period="latest", ...)``.
        window (DateWindow): Maturity dates to include, possibly starting in the past.
        names (Iterable[str | None]): The company's names, such as its Korean and English
            names, to tell its own issues from those of subsidiaries.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        MaturitySchedule: Maturities and the ladder; empty when the reports list neither.
    """
    found = await first_available(
        resolved,
        lambda ref: _latest_tables(company, ref, fetch_service=fetch_service, today=today),
        attempts=probe_attempts(resolved),
    )
    if found is None and (prior := prior_annual(resolved.candidates[0])) is not None:
        # The first probe already read this report's issuance record; a caching source
        # answers it again without a call.
        tables = await _latest_tables(company, prior, fetch_service=fetch_service, today=today)
        found = None if tables is None else (prior, tables)
    if found is None:
        return MaturitySchedule()
    ref, (issues, balances, earlier) = found
    rows = [row for batch in (issues, earlier) if batch for row in batch]
    listed = maturities(rows, company_names(names), start=window.start, until=window.end)
    return MaturitySchedule(listed, ref, build_ladder(BONDS, balances or []))
