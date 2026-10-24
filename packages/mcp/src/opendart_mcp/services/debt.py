"""get_debt_profile and the calendar's debt maturities, from periodic reports.

The logic lives in ``opendart_analysis.debt``. This adapter resolves the company and period,
binds the workflows to the gateway and the server clock (periodic-report lifetimes, as
``services.extracts`` uses), and projects their values into the unchanged output models.
Presentation stays here: concise results list at most ``CONCISE_ISSUES`` open issues, without
fully redeemed issues, underwriters, the company's own name as issuer, or filed ladder
columns, and the notes point to ``response_format`` and get_financials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis import debt
from opendart_analysis.errors import AnalysisError
from opendart_analysis.extracts import checked
from opendart_mcp.core.errors import from_analysis
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.debt import DebtMaturity, DebtProfileResult, Issuance
from opendart_mcp.services.debt_tables import derived, ladder_entry
from opendart_mcp.services.periods import resolve_period

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence
    from datetime import date

    from opendart_analysis.debt import DebtProfile, Issue, Maturity
    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Period
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.models.debt import LadderEntry
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.periods import ResolvedPeriod

_SCOPE: Final = (
    "Covers debt securities only; bank loans and total borrowings are in get_financials."
)
CONCISE_ISSUES: Final = 30
"""Most open issues a concise result lists, earliest maturity first."""


async def _translated[T](call: Awaitable[T]) -> T:
    """Await an analysis workflow, translating its failures into server errors.

    Args:
        call (Awaitable[T]): Workflow call; gateway failures pass through unchanged.

    Returns:
        T: The workflow's result.

    Raises:
        ServerError: An analysis failure, translated.
    """
    try:
        return await call
    except AnalysisError as error:
        raise from_analysis(error) from error


def _names(company: Company) -> tuple[str | None, str]:
    """List the company's names, to tell its own issues from those of other entities.

    Args:
        company (Company): Resolved company.

    Returns:
        tuple[str | None, str]: Korean and English names.
    """
    return company.ref.korean_name, company.ref.name


def _issuance(item: Issue, *, detailed: bool) -> Issuance:
    """Describe one issue; concise results omit the underwriter and the company's own name.

    Args:
        item (Issue): Issue from ``opendart_analysis.debt``.
        detailed (bool): Whether to add the underwriter and always name the issuer.

    Returns:
        Issuance: Output issue.
    """
    return Issuance(
        issued=item.issued,
        security=item.security,
        method=item.method,
        amount=item.amount,
        coupon=item.coupon,
        rating=item.rating,
        rating_agency=item.rating_agency,
        maturity=item.maturity,
        redeemed=item.redeemed,
        issuer=item.issuer if detailed else item.other_issuer,
        underwriter=item.underwriter if detailed else None,
    )


def _issues(issues: Sequence[Issue], *, detailed: bool) -> tuple[list[Issuance], int]:
    """Describe the issuance record; concise results keep issues not fully redeemed.

    Args:
        issues (Sequence[Issue]): Issues by maturity.
        detailed (bool): Whether to keep redeemed issues and every field.

    Returns:
        tuple[list[Issuance], int]: Issues by maturity, and how many redeemed ones were left
            out.
    """
    kept = [item for item in issues if detailed or item.redeemed != "yes"]
    return [_issuance(item, detailed=detailed) for item in kept], len(issues) - len(kept)


def _profile(
    company: Company,
    profile: DebtProfile,
    resolved: ResolvedPeriod,
    *,
    detailed: bool,
    as_of: date,
) -> DebtProfileResult:
    """Describe a profile.

    Args:
        company (Company): Resolved company.
        profile (DebtProfile): Profile from ``opendart_analysis.debt``.
        resolved (ResolvedPeriod): Period candidates, for notes.
        detailed (bool): Whether to return every field.
        as_of (date): Server date.

    Returns:
        DebtProfileResult: Ladder, issuance record, and derived figures.
    """
    ref = profile.ref
    ladder = [ladder_entry(entry, detailed=detailed) for entry in profile.ladder]
    issues, omitted = _issues(profile.issues, detailed=detailed)
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
        source_filings=[SourceFiling.of(s.filing_number, s.title) for s in profile.sources],
        notes=[*notes, _SCOPE],
        fiscal_year=ref.fiscal_year,
        period=ref.period,
        period_end=ref.end_date,
        ladder=ladder,
        issuance=shown,
        derived=derived(profile.figures),
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
    found = await _translated(
        debt.debt_profile(
            resolved_company,
            resolved,
            names=_names(resolved_company),
            fetch_service=service_fetch(state.require_gateway),
            today=state.today(),
        )
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


def _maturity(item: Maturity) -> DebtMaturity:
    """Describe one maturity.

    Args:
        item (Maturity): Maturity from ``opendart_analysis.debt``.

    Returns:
        DebtMaturity: Output maturity.
    """
    return DebtMaturity(
        date=item.date,
        instrument=item.instrument,
        face_value=item.face_value,
        filing_number=item.filing_number,
        coupon=item.coupon,
        redeemed=item.redeemed,
        issuer=item.issuer,
    )


async def maturity_schedule(
    state: AppState, company: Company, *, window: DateWindow
) -> MaturitySchedule:
    """List debt securities that mature in a calendar window, with the corporate-bond ladder.

    Reads the latest periodic report's issuance record and corporate-bond balance and, for a
    quarterly or half-year report, the previous annual report's issuance record (see
    ``opendart_analysis.debt.maturity_schedule``). Costs one cached filing search and two or
    three upstream calls per period probed.

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
    schedule = await _translated(
        debt.maturity_schedule(
            company,
            resolved,
            window=window,
            names=_names(company),
            fetch_service=service_fetch(state.require_gateway),
            today=state.today(),
        )
    )
    bonds = None if schedule.bonds is None else ladder_entry(schedule.bonds, detailed=False)
    return MaturitySchedule(list(map(_maturity, schedule.maturities)), schedule.period, bonds)
