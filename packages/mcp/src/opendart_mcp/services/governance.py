"""get_governance: audit, board, executives, pay, and employees from one periodic report.

``opendart_analysis.governance`` fetches the requested sections' services for the resolved
period and computes the sections and flags. This adapter resolves the company and period,
binds fetching to the gateway (``core.upstream.service_fetch``, whose lifetimes follow the
period's volatility as ``periodic_ttl`` does), and projects the analysis values into the
unchanged output models. Concise results drop unregistered executives (with a note), personal
details, opinion history, prior-year non-audit services, filed remarks, stock-based pay, and
non-headline workforce rows; the analysis values keep them all.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

from opendart_analysis.errors import AnalysisError
from opendart_analysis.extracts import checked
from opendart_analysis.governance import (
    DEFAULT_SECTIONS,
    governance_facts,
    headline,
    scale_note,
)
from opendart_mcp.core.errors import from_analysis
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.governance import (
    AuditFacts,
    BoardFacts,
    Compensation,
    Employees,
    Executive,
    GovernanceFlag,
    GovernanceResult,
)
from opendart_mcp.services.periods import resolve_period

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Mapping, Sequence

    from opendart_analysis import governance as analysis
    from opendart_analysis.domain.types import Period
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import CompanyRef, ResponseFormat
    from opendart_mcp.models.governance import GovernanceSection

__all__ = ["DEFAULT_SECTIONS", "GovernanceQuery", "governance"]


def _audit(facts: analysis.AuditFacts, fiscal_year: int, *, detailed: bool) -> AuditFacts:
    """Show the audit section; concise results keep the current year's non-audit services.

    Args:
        facts (analysis.AuditFacts): Audit facts.
        fiscal_year (int): Fiscal year of the report's current term.
        detailed (bool): Keep opinion history, prior-year services, and the work covered.

    Returns:
        AuditFacts: Output audit section.
    """
    if detailed:
        return AuditFacts.model_validate(asdict(facts))
    concise = replace(
        facts,
        fees=tuple(replace(fee, scope=None) for fee in facts.fees),
        non_audit_services=tuple(
            service for service in facts.non_audit_services if service.fiscal_year == fiscal_year
        ),
    )
    return AuditFacts.model_validate(asdict(concise)).model_copy(update={"history": None})


def _executive(person: analysis.Executive, *, detailed: bool) -> Executive:
    """Show one executive; concise results leave out personal details and career.

    Args:
        person (analysis.Executive): Executive.
        detailed (bool): Keep every field.

    Returns:
        Executive: Output executive.
    """
    if not detailed:
        person = replace(
            person,
            gender=None,
            born=None,
            career=None,
            largest_shareholder_relation=None,
            tenure=None,
            role_as_filed=None,
        )
    return Executive.model_validate(asdict(person))


def _executives(
    people: Sequence[analysis.Executive] | None, *, detailed: bool
) -> tuple[list[Executive] | None, int]:
    """Show executives; concise results keep registered officers only.

    Args:
        people (Sequence[analysis.Executive] | None): Every named executive, or None.
        detailed (bool): Keep unregistered executives and personal details.

    Returns:
        tuple[list[Executive] | None, int]: Executives, None when none is left, and how many
            unregistered executives were left out.
    """
    everyone = list(people or ())
    shown = everyone if detailed else [p for p in everyone if p.role != "unregistered"]
    found = [_executive(person, detailed=detailed) for person in shown]
    return found or None, len(everyone) - len(shown)


def _compensation(pay: analysis.Compensation, *, detailed: bool) -> Compensation:
    """Show pay; concise results drop stock-based pay, filed remarks, and pay outside totals.

    Args:
        pay (analysis.Compensation): Pay facts.
        detailed (bool): Keep every field.

    Returns:
        Compensation: Output pay section.
    """
    if not detailed:
        unregistered = pay.unregistered_executives
        pay = replace(
            pay,
            by_type=tuple(replace(group, stock_based=None, note=None) for group in pay.by_type),
            directors_over_500m=tuple(
                replace(person, not_in_total=None) for person in pay.directors_over_500m
            ),
            top_paid=tuple(replace(person, not_in_total=None) for person in pay.top_paid),
            unregistered_executives=None
            if unregistered is None
            else replace(unregistered, stock_based=None, note=None),
        )
    return Compensation.model_validate(asdict(pay))


def _employees(staff: analysis.Employees, *, detailed: bool) -> Employees:
    """Show the workforce; concise results list the headline rows that make the totals.

    Args:
        staff (analysis.Employees): Workforce facts.
        detailed (bool): List every row.

    Returns:
        Employees: Output workforce section.
    """
    if not detailed:
        staff = replace(staff, groups=tuple(headline(staff.groups)))
    return Employees.model_validate(asdict(staff))


def _notes(
    sections: Sequence[GovernanceSection],
    shown: Mapping[GovernanceSection, object | None],
    *,
    label: str,
    scale: str | None,
    omitted: int,
) -> list[str]:
    """Explain fee units, omitted executives, and sections without data, in section order.

    Args:
        sections (Sequence[GovernanceSection]): Requested sections.
        shown (Mapping[GovernanceSection, object | None]): Output sections by name.
        label (str): Period label of the report, such as FY2025.
        scale (str | None): Note on audit-fee units, if any.
        omitted (int): Unregistered executives left out of a concise result.

    Returns:
        list[str]: Notes.
    """
    notes: list[str] = []
    for section in sections:
        if section == "audit" and scale:
            notes.append(scale)
        if section == "executives" and omitted:
            notes.append(
                f"{omitted} unregistered executives are omitted; response_format='detailed' lists them."
            )
        if shown[section] is None:
            notes.append(f"No {section} data in the {label} report.")
    if "audit" not in sections:
        notes.append("Flags come from the audit section, which was not requested.")
    return notes


def _result(
    facts: analysis.GovernanceFacts,
    *,
    company: CompanyRef,
    as_of: dt.date,
    detailed: bool,
    period_note: str | None,
) -> GovernanceResult:
    """Project analysis facts into the output model.

    Args:
        facts (analysis.GovernanceFacts): Facts from the analysis workflow.
        company (CompanyRef): Resolved company.
        as_of (dt.date): Server date.
        detailed (bool): Whether the result is detailed.
        period_note (str | None): Note from period resolution, which comes first.

    Returns:
        GovernanceResult: Result.
    """
    ref = facts.ref
    audit = None if facts.audit is None else _audit(facts.audit, ref.fiscal_year, detailed=detailed)
    board = None if facts.board is None else BoardFacts.model_validate(asdict(facts.board))
    executives, omitted = _executives(facts.executives, detailed=detailed)
    pay = facts.compensation
    compensation = None if pay is None else _compensation(pay, detailed=detailed)
    staff = facts.employees
    employees = None if staff is None else _employees(staff, detailed=detailed)
    shown: dict[GovernanceSection, object | None] = {
        "audit": audit,
        "board": board,
        "executives": executives,
        "compensation": compensation,
        "employees": employees,
    }
    scale = scale_note(audit.fee_scale) if audit is not None and audit.fees else None
    notes = _notes(facts.sections, shown, label=ref.label, scale=scale, omitted=omitted)
    return GovernanceResult(
        company=company,
        as_of=as_of,
        source_filings=[SourceFiling.of(s.filing_number, s.title) for s in facts.sources],
        sections=list(facts.sections),
        fiscal_year=ref.fiscal_year,
        period=ref.period,
        period_end=ref.end_date,
        audit=audit,
        board=board,
        executives=executives,
        compensation=compensation,
        employees=employees,
        flags=[GovernanceFlag(kind=flag.kind, detail=flag.detail) for flag in facts.flags],
        notes=[n for n in (period_note, *notes) if n],
    )


@dataclass(frozen=True, slots=True)
class GovernanceQuery:
    """What a get_governance call asks for.

    Attributes:
        sections (Sequence[GovernanceSection]): Sections to fetch; duplicates are ignored.
        fiscal_year (int | None): Requested fiscal year, if any.
        period (Period): Requested period; annual reports carry the full audit opinion.
        response_format (ResponseFormat): ``detailed`` adds opinion history, unregistered
            executives, every workforce row, and filed remarks.
    """

    sections: Sequence[GovernanceSection] = DEFAULT_SECTIONS
    fiscal_year: int | None = None
    period: Period = "FY"
    response_format: ResponseFormat = "concise"


async def governance(
    state: AppState,
    company: str,
    query: GovernanceQuery | None = None,
    *,
    progress: Progress = no_progress,
) -> GovernanceResult:
    """Collect audit and governance facts from one periodic report.

    Args:
        state (AppState): Server state.
        company (str): Name, stock code, or corp code.
        query (GovernanceQuery | None): Sections, period, and detail; None uses defaults.
        progress (Progress): Reports progress.

    Returns:
        GovernanceResult: Requested sections and flags, or an empty result with a note.
    """
    query = query or GovernanceQuery()
    wanted = list(dict.fromkeys(query.sections))
    resolved_company = await state.companies.resolve(company, progress=progress)
    resolved = await resolve_period(
        state, resolved_company, period=query.period, fiscal_year=query.fiscal_year
    )
    await progress(f"Reading {", ".join(wanted)} for {resolved_company.ref.name}")
    try:
        facts = await governance_facts(
            resolved_company,
            resolved,
            sections=wanted,
            fetch_service=service_fetch(state.require_gateway),
            today=state.today(),
        )
    except AnalysisError as error:
        raise from_analysis(error) from error
    if facts is None:
        note = f"OpenDART has no {", ".join(wanted)} tables for {checked(resolved)}."
        notes = [n for n in (resolved.note, note) if n]
        return GovernanceResult(
            company=resolved_company.ref, as_of=state.today(), sections=wanted, notes=notes
        )
    return _result(
        facts,
        company=resolved_company.ref,
        as_of=state.today(),
        detailed=query.response_format == "detailed",
        period_note=resolved.note,
    )
