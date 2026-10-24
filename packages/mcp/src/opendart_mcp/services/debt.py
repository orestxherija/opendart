"""get_debt_profile and the calendar's debt maturities, from periodic reports.

The profile fetches six periodic-report services concurrently for one resolved period: five
outstanding-balance tables (corporate bonds, short-term bonds, commercial paper, hybrid
securities, contingent capital securities) and the issuance record. ``maturity_schedule``
gives the corporate-action calendar the maturities listed in recent issuance records, which
cover only recently issued securities, and the latest corporate-bond ladder, which covers
every bond outstanding at the period end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.periods import FIRST_FISCAL_YEAR, PeriodRef
from opendart_mcp.core.progress import no_progress
from opendart_mcp.models.debt import DebtProfileResult
from opendart_mcp.services.debt_issuance import (
    ISSUANCE_SERVICE,
    company_key,
    issuance,
    maturities,
)
from opendart_mcp.services.debt_tables import LADDERS, build_ladder, derive
from opendart_mcp.services.extracts import (
    checked,
    fetch_records,
    gather_all,
    probe_attempts,
    sources,
    text,
)
from opendart_mcp.services.periods import first_available, resolve_period

if TYPE_CHECKING:
    from datetime import date

    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.domain.types import Period
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.models.debt import DebtMaturity, LadderEntry
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.debt_tables import LadderSpec
    from opendart_mcp.services.periods import ResolvedPeriod

_SCOPE: Final = (
    "Covers debt securities only; bank loans and total borrowings are in get_financials."
)
CONCISE_ISSUES: Final = 30
"""Most open issues a concise result lists, earliest maturity first."""
BONDS: Final = next(spec for spec in LADDERS if spec.instrument == "corporate_bonds")
"""Corporate-bond balance table, read with the calendar's maturities."""
type _Tables = tuple[list[object] | None, list[object] | None, list[object] | None]
"""A period's issuance rows and corporate-bond balance rows, and prior annual issuance rows."""


@dataclass(frozen=True, slots=True)
class DebtTables:
    """The six debt tables of one periodic report.

    Attributes:
        balances (tuple[tuple[LadderSpec, list[object]], ...]): Balance rows per instrument,
            in ladder order.
        issues (list[object]): Issuance-record rows.
    """

    balances: tuple[tuple[LadderSpec, list[object]], ...]
    issues: list[object]

    def filing_numbers(self) -> list[str | None]:
        """List the filing number of every row.

        Returns:
            list[str | None]: Filing numbers in table order.
        """
        rows = [*(row for _, rows in self.balances for row in rows), *self.issues]
        return [text(row, "filing_number") for row in rows]


async def fetch_tables(state: AppState, company: Company, ref: PeriodRef) -> DebtTables | None:
    """Fetch the six debt tables of one period concurrently.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        DebtTables | None: The tables, or None when OpenDART has none of them.
    """
    services = (*(spec.service for spec in LADDERS), ISSUANCE_SERVICE)
    found = await gather_all(
        fetch_records(state, name, company=company, ref=ref) for name in services
    )
    if all(rows is None for rows in found):
        return None
    tables = [rows or [] for rows in found]
    return DebtTables(tuple(zip(LADDERS, tables[:-1], strict=True)), tables[-1])


def company_names(company: Company) -> frozenset[str]:
    """Collect comparable keys of the company's names, to spot issues by other entities.

    Args:
        company (Company): Resolved company.

    Returns:
        frozenset[str]: Name keys.
    """
    names = (company.ref.korean_name, company.ref.name)
    return frozenset(key for key in map(company_key, names) if key)


def _profile(
    company: Company,
    found: tuple[PeriodRef, DebtTables],
    resolved: ResolvedPeriod,
    *,
    detailed: bool,
    as_of: date,
) -> DebtProfileResult:
    """Assemble the profile from one period's tables.

    Args:
        company (Company): Resolved company.
        found (tuple[PeriodRef, DebtTables]): Period with data and its tables.
        resolved (ResolvedPeriod): Period candidates, for notes and source titles.
        detailed (bool): Whether to return every field.
        as_of (date): Server date.

    Returns:
        DebtProfileResult: Ladder, issuance record, and derived figures.
    """
    ref, tables = found
    ladder = [
        entry
        for spec, rows in tables.balances
        if (entry := build_ladder(spec, rows, detailed=detailed)) is not None
    ]
    issues, omitted = issuance(tables.issues, company_names(company), detailed=detailed)
    shown = issues if detailed else issues[:CONCISE_ISSUES]
    notes = [resolved.note] if resolved.note else []
    if not ladder:
        notes.append(f"No outstanding balances are reported in {ref.label}.")
    if omitted:
        notes.append(
            f"{omitted} fully redeemed issues are omitted; response_format='detailed' lists them."
        )
    if len(shown) < len(issues):
        notes.append(
            f"{len(issues) - len(shown)} later-maturing open issues are omitted; response_format='detailed' lists them."
        )
    return DebtProfileResult(
        company=company.ref,
        as_of=as_of,
        source_filings=sources(tables.filing_numbers(), resolved.report),
        notes=[*notes, _SCOPE],
        fiscal_year=ref.fiscal_year,
        period=ref.period,
        period_end=ref.end_date,
        ladder=ladder,
        issuance=shown,
        derived=derive(ladder),
    )


async def debt_profile(
    state: AppState,
    company: str,
    *,
    period: Period = "latest",
    fiscal_year: int | None = None,
    response_format: ResponseFormat = "concise",
    progress: Progress = no_progress,
) -> DebtProfileResult:
    """Build a company's debt profile from one periodic report.

    Args:
        state (AppState): Server state.
        company (str): Name, stock code, or corp code.
        period (Period): Requested period; ``latest`` is the newest periodic report.
        fiscal_year (int | None): Requested fiscal year, if any.
        response_format (ResponseFormat): ``detailed`` adds redeemed issues, underwriters,
            and every maturity column as filed.
        progress (Progress): Reports progress.

    Returns:
        DebtProfileResult: Ladder, issuance record, and derived figures, or an empty result
            with a note when the report has no debt tables.
    """
    resolved_company = await state.companies.resolve(company, progress=progress)
    resolved = await resolve_period(state, resolved_company, period=period, fiscal_year=fiscal_year)
    await progress(f"Reading debt tables for {resolved_company.ref.name}")
    found = await first_available(
        resolved,
        lambda ref: fetch_tables(state, resolved_company, ref),
        attempts=probe_attempts(resolved),
    )
    if found is None:
        note = f"OpenDART has no debt-security tables for {checked(resolved)}; the company may have no bonds, commercial paper, or hybrid securities outstanding. {_SCOPE}"
        notes = [resolved.note, note] if resolved.note else [note]
        return DebtProfileResult(company=resolved_company.ref, notes=notes, as_of=state.today())
    detailed = response_format == "detailed"
    return _profile(resolved_company, found, resolved, detailed=detailed, as_of=state.today())


@dataclass(frozen=True, slots=True)
class MaturitySchedule:
    """Debt maturities in a calendar window, with the reports they come from.

    Attributes:
        maturities (list[DebtMaturity]): Maturities, earliest first, each issue once.
        period (PeriodRef | None): Latest period read, or None when no report had debt
            tables.
        bonds (LadderEntry | None): Corporate bonds outstanding at that period's end by
            remaining maturity, or None when none are reported.
    """

    maturities: list[DebtMaturity]
    period: PeriodRef | None = None
    bonds: LadderEntry | None = None


def _prior_annual(ref: PeriodRef) -> PeriodRef | None:
    """Name the annual report before a quarterly or half-year period.

    Args:
        ref (PeriodRef): Latest period.

    Returns:
        PeriodRef | None: The previous fiscal year, or None for annual or first-year periods.
    """
    if ref.period == "FY" or ref.fiscal_year <= FIRST_FISCAL_YEAR:
        return None
    return PeriodRef(ref.fiscal_year - 1, "FY")


async def _schedule_tables(state: AppState, company: Company, ref: PeriodRef) -> _Tables:
    """Fetch a period's issuance record and bond balances, and the prior annual record.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Candidate latest period.

    Returns:
        _Tables: Issuance rows, corporate-bond balance rows, and the prior annual report's
            issuance rows when the period is not annual; None where OpenDART has no data.
    """
    refs = [(ISSUANCE_SERVICE, ref), (BONDS.service, ref)]
    if (prior := _prior_annual(ref)) is not None:
        refs.append((ISSUANCE_SERVICE, prior))
    issues, balances, *earlier = await gather_all(
        fetch_records(state, name, company=company, ref=period) for name, period in refs
    )
    return issues, balances, earlier[0] if earlier else None


async def _latest_tables(state: AppState, company: Company, ref: PeriodRef) -> _Tables | None:
    """Fetch a candidate latest period's tables, for probing.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Candidate latest period.

    Returns:
        _Tables | None: The tables, or None when the period itself has neither an issuance
            record nor bond balances, whatever the prior annual record holds.
    """
    tables = await _schedule_tables(state, company, ref)
    return None if tables[0] is None and tables[1] is None else tables


async def maturity_schedule(
    state: AppState, company: Company, *, window: DateWindow
) -> MaturitySchedule:
    """List debt securities that mature in a calendar window, with the corporate-bond ladder.

    Reads the issuance record and the corporate-bond balance of the latest periodic report
    and, when that report is a quarterly or half-year one, the issuance record of the
    previous annual report, so issues from the current and prior fiscal years are covered;
    older issues appear only when the company lists them again, so the ladder is the
    complete view. Candidate periods are probed like get_debt_profile when no report is in
    the filing index; when none has tables of its own, the annual report before the first
    candidate is read as the latest. Fully redeemed issues are skipped; partly redeemed ones
    keep their original face value with their status. Costs one cached filing search and
    two or three upstream calls per period probed.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company, from ``state.companies.resolve``.
        window (DateWindow): Maturity dates to include, from the calendar's first date
            (which may be in the past) to its horizon.

    Returns:
        MaturitySchedule: Maturities and the ladder; empty when the reports list neither.

    Raises:
        ServerError: Upstream failures such as quota exhaustion or a missing API key, from
            the gateway; "no data" is an empty schedule, not an error.
    """
    resolved = await resolve_period(state, company, period="latest", fiscal_year=None)
    found = await first_available(
        resolved,
        lambda ref: _latest_tables(state, company, ref),
        attempts=probe_attempts(resolved),
    )
    if found is None and (prior := _prior_annual(resolved.candidates[0])) is not None:
        # The first probe already read (and cached) this report's issuance record.
        tables = await _latest_tables(state, company, prior)
        found = None if tables is None else (prior, tables)
    if found is None:
        return MaturitySchedule([])
    ref, (issues, balances, earlier) = found
    rows = [row for batch in (issues, earlier) if batch for row in batch]
    listed = maturities(rows, company_names(company), start=window.start, until=window.end)
    bonds = build_ladder(BONDS, balances or [], detailed=False)
    return MaturitySchedule(listed, ref, bonds)
