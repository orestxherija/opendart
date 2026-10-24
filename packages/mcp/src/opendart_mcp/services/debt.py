"""get_debt_profile: debt-security ladders, issuance, and derived figures from a periodic report.

The logic lives in ``opendart_analysis.debt``. This adapter resolves the company and period,
binds the workflow to the gateway and the server clock (periodic-report lifetimes through
``core.upstream.service_fetch``), and projects its values into the unchanged output models.
Presentation stays here: concise results list at most ``CONCISE_ISSUES`` open issues, without
fully redeemed issues, underwriters, the company's own name as issuer, or filed ladder
columns, and the notes point to ``response_format`` and get_financials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis import debt
from opendart_analysis.errors import AnalysisError
from opendart_analysis.extracts import checked
from opendart_mcp.core.errors import from_analysis
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.debt import (
    DebtDerived,
    DebtProfileResult,
    FiledBucket,
    Issuance,
    LadderBucket,
    LadderEntry,
)
from opendart_mcp.services.periods import resolve_period

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence
    from datetime import date

    from opendart_analysis.debt import DebtFigures, DebtProfile, Issue, Ladder
    from opendart_analysis.domain.types import Period
    from opendart_analysis.reports import ResolvedPeriod
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.services.companies import Company

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


def _ladder_entry(ladder: Ladder, *, detailed: bool) -> LadderEntry:
    """Describe one instrument's ladder; only detailed results list every filed column.

    Args:
        ladder (Ladder): Ladder from ``opendart_analysis.debt``.
        detailed (bool): Whether to add every maturity column as filed.

    Returns:
        LadderEntry: Output entry.
    """
    filed = [
        FiledBucket(
            label=column.label, public=column.public, private=column.private, total=column.total
        )
        for column in ladder.filed
    ]
    return LadderEntry(
        instrument=ladder.instrument,
        buckets=[
            LadderBucket(maturity_bucket=b.maturity_bucket, amount=b.amount) for b in ladder.buckets
        ],
        total=ladder.total,
        public=ladder.public,
        private=ladder.private,
        issuance_limit=ladder.issuance_limit,
        remaining_limit=ladder.remaining_limit,
        filed=filed if detailed else None,
    )


def _derived(figures: DebtFigures) -> DebtDerived:
    """Describe derived debt figures.

    Args:
        figures (DebtFigures): Figures from ``opendart_analysis.debt.derive``.

    Returns:
        DebtDerived: Output figures; empty for an empty ladder.
    """
    return DebtDerived(
        total_debt_securities=figures.total_debt_securities,
        due_within_1y=figures.due_within_1y,
        due_within_1y_pct=figures.due_within_1y_pct,
    )


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
    ladder = [_ladder_entry(entry, detailed=detailed) for entry in profile.ladder]
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
        derived=_derived(profile.figures),
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
