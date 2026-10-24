"""get_governance: audit, board, executives, pay, and employees from one periodic report.

Each section has its own services, and only the requested sections are fetched, all at once
for the resolved period. The remuneration services for individuals prefer Ver 2.0 and fall
back to Ver 1.0 when Ver 2.0 has no data. Flags come from the audit section: a modified
opinion, going-concern language, and an auditor change from the prior fiscal year, which
costs one extra call when the report does not list the prior year's auditor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.periods import FIRST_FISCAL_YEAR, PeriodRef
from opendart_mcp.core.progress import no_progress
from opendart_mcp.models.governance import GovernanceResult
from opendart_mcp.services.extracts import (
    checked,
    fetch_records,
    fetch_response,
    gather_all,
    probe_attempts,
    records,
    sources,
    text,
)
from opendart_mcp.services.governance_audit import (
    audit_facts,
    audit_flags,
    changed,
    opinion_rows,
    scale_note,
)
from opendart_mcp.services.governance_pay import PayTables, compensation
from opendart_mcp.services.governance_people import board, employees, executives
from opendart_mcp.services.periods import first_available, resolve_period

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from opendart_analysis.domain.types import Period
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.models.governance import (
        AuditFacts,
        AuditYear,
        BoardFacts,
        Compensation,
        Employees,
        Executive,
        GovernanceFlag,
        GovernanceSection,
    )
    from opendart_mcp.services.companies import Company

    type Tables = Mapping[str, list[object] | None]

DEFAULT_SECTIONS: Final[tuple[GovernanceSection, ...]] = ("audit", "board")
OPINIONS: Final = "accnut_adtor_nm_nd_adt_opinion"
FEES: Final = "adt_servc_cncls_sttus"
NON_AUDIT: Final = "accnut_adtor_non_adt_servc_cncls_sttus"
DIRECTORS_PAY: Final = "directors_over_500m"
TOP_PAY: Final = "top_paid"
SECTION_SERVICES: Final[dict[GovernanceSection, tuple[str, ...]]] = {
    "audit": (OPINIONS, FEES, NON_AUDIT),
    "board": ("outcmpny_drctr_nd_change_sttus",),
    "executives": ("exctv_sttus",),
    "compensation": (
        "drctr_adt_all_mendng_sttus_gmtsck_confm_amount",
        "hmv_audit_all_sttus",
        "drctr_adt_all_mendng_sttus_mendng_pymntamt_ty_cl",
        "unrst_exctv_mendng_sttus",
    ),
    "employees": ("emp_sttus",),
}
"""Upstream services per section; compensation also reads two versioned services."""

VERSIONED: Final = (
    (DIRECTORS_PAY, "hmv_audit_indvdl_by_sttus_v2", "hmv_audit_indvdl_by_sttus"),
    (TOP_PAY, "indvdl_by_pay_v2", "indvdl_by_pay"),
)
"""Individual pay: result key, preferred Ver 2.0 service, Ver 1.0 fallback."""


async def versioned(
    state: AppState, services: tuple[str, str], *, company: Company, ref: PeriodRef
) -> list[object] | None:
    """Fetch individual pay from the Ver 2.0 service, or from Ver 1.0 when it has none.

    Args:
        state (AppState): Server state.
        services (tuple[str, str]): Ver 2.0 and Ver 1.0 service names.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        list[object] | None: Ver 2.0 ``group`` items or Ver 1.0 records; None when neither
            has data.
    """
    newer, older = services
    response = await fetch_response(state, newer, company=company, ref=ref)
    found: list[object] = records(response, "group") if response is not None else []
    return found or await fetch_records(state, older, company=company, ref=ref)


async def fetch_tables(
    state: AppState, company: Company, ref: PeriodRef, *, sections: Sequence[GovernanceSection]
) -> dict[str, list[object] | None] | None:
    """Fetch the services the requested sections need, concurrently.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.
        sections (Sequence[GovernanceSection]): Requested sections.

    Returns:
        dict[str, list[object] | None] | None: Records by service (and individual-pay key),
            or None when no service has data.
    """
    names = [name for section in sections for name in SECTION_SERVICES[section]]
    calls = [fetch_records(state, name, company=company, ref=ref) for name in names]
    if "compensation" in sections:
        names += [key for key, *_ in VERSIONED]
        calls += [
            versioned(state, (newer, older), company=company, ref=ref)
            for _, newer, older in VERSIONED
        ]
    found = await gather_all(calls)
    if all(rows is None for rows in found):
        return None
    return dict(zip(names, found, strict=True))


@dataclass(slots=True)
class _Built:
    """Sections built from one report's tables."""

    tables: Tables
    ref: PeriodRef
    detailed: bool
    audit: AuditFacts | None = None
    history: list[AuditYear] = field(default_factory=list)
    board: BoardFacts | None = None
    executives: list[Executive] | None = None
    compensation: Compensation | None = None
    employees: Employees | None = None
    notes: list[str] = field(default_factory=list)

    def rows(self, service: str) -> list[object]:
        """Return a service's records.

        Args:
            service (str): Service name or individual-pay key.

        Returns:
            list[object]: Records, empty when the service had no data.
        """
        return self.tables.get(service) or []


def _audit(built: _Built) -> None:
    """Build the audit section.

    Args:
        built (_Built): Sections so far; updated in place.
    """
    year = built.ref.fiscal_year
    built.history = opinion_rows(built.rows(OPINIONS), year)
    built.audit = audit_facts(
        built.history,
        built.rows(FEES),
        built.rows(NON_AUDIT),
        fiscal_year=year,
        detailed=built.detailed,
    )
    note = scale_note(built.audit.fee_scale) if built.audit and built.audit.fees else None
    if note:
        built.notes.append(note)


def _board(built: _Built) -> None:
    """Build the board section.

    Args:
        built (_Built): Sections so far; updated in place.
    """
    built.board = board(built.rows("outcmpny_drctr_nd_change_sttus"))


def _executives(built: _Built) -> None:
    """Build the executives section.

    Args:
        built (_Built): Sections so far; updated in place.
    """
    people, omitted = executives(built.rows("exctv_sttus"), detailed=built.detailed)
    built.executives = people or None
    if omitted:
        built.notes.append(
            f"{omitted} unregistered executives are omitted; response_format='detailed' lists them."
        )


def _compensation(built: _Built) -> None:
    """Build the compensation section.

    Args:
        built (_Built): Sections so far; updated in place.
    """
    services = SECTION_SERVICES["compensation"]
    approved, paid, by_type, unregistered = (built.rows(name) for name in services)
    tables = PayTables(
        approved, paid, by_type, built.rows(DIRECTORS_PAY), built.rows(TOP_PAY), unregistered
    )
    built.compensation = compensation(tables, detailed=built.detailed)


def _employees(built: _Built) -> None:
    """Build the employees section.

    Args:
        built (_Built): Sections so far; updated in place.
    """
    built.employees = employees(built.rows("emp_sttus"), detailed=built.detailed)


_BUILDERS: Final[dict[GovernanceSection, Callable[[_Built], None]]] = {
    "audit": _audit,
    "board": _board,
    "executives": _executives,
    "compensation": _compensation,
    "employees": _employees,
}


def build(
    tables: Tables, ref: PeriodRef, sections: Sequence[GovernanceSection], *, detailed: bool
) -> _Built:
    """Build the requested sections and note the ones without data.

    Args:
        tables (Tables): Records by service.
        ref (PeriodRef): Period of the report.
        sections (Sequence[GovernanceSection]): Requested sections.
        detailed (bool): Whether to return every field.

    Returns:
        _Built: Sections and notes.
    """
    built = _Built(tables, ref, detailed)
    for section in sections:
        _BUILDERS[section](built)
        if getattr(built, section) is None:
            built.notes.append(f"No {section} data in the {ref.label} report.")
    return built


async def _prior_auditor(state: AppState, company: Company, built: _Built) -> list[object]:
    """Look up last fiscal year's auditor when the report does not list it.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        built (_Built): Sections so far; the audit section is updated in place.

    Returns:
        list[object]: Records of the extra call, for provenance; empty when skipped.
    """
    audit = built.audit
    year = built.ref.fiscal_year - 1
    if audit is None or audit.auditor is None or audit.prior_auditor or year < FIRST_FISCAL_YEAR:
        return []
    found = await fetch_records(state, OPINIONS, company=company, ref=PeriodRef(year, "FY")) or []
    rows = [row for row in opinion_rows(found, year) if row.fiscal_year == year and row.auditor]
    prior = rows[0].auditor if rows else None
    built.audit = audit.model_copy(
        update={
            "prior_auditor": prior,
            "auditor_changed_vs_prior_year": changed(audit.auditor, prior),
        }
    )
    return found


def _flags(built: _Built, sections: Sequence[GovernanceSection]) -> list[GovernanceFlag]:
    """Derive flags from the audit section.

    Args:
        built (_Built): Built sections; a note is added when audit was not requested.
        sections (Sequence[GovernanceSection]): Requested sections.

    Returns:
        list[GovernanceFlag]: Flags.
    """
    if "audit" not in sections:
        built.notes.append("Flags come from the audit section, which was not requested.")
        return []
    if built.audit is None:
        return []
    ref = built.ref
    return audit_flags(built.audit, built.history, fiscal_year=ref.fiscal_year, label=ref.label)


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
    found = await first_available(
        resolved,
        lambda ref: fetch_tables(state, resolved_company, ref, sections=wanted),
        attempts=probe_attempts(resolved),
    )
    if found is None:
        note = f"OpenDART has no {", ".join(wanted)} tables for {checked(resolved)}."
        notes = [n for n in (resolved.note, note) if n]
        return GovernanceResult(
            company=resolved_company.ref, as_of=state.today(), sections=wanted, notes=notes
        )
    ref, tables = found
    built = build(tables, ref, wanted, detailed=query.response_format == "detailed")
    extra = await _prior_auditor(state, resolved_company, built)
    rows = [*(row for batch in tables.values() for row in batch or ()), *extra]
    flags = _flags(built, wanted)
    return GovernanceResult(
        company=resolved_company.ref,
        as_of=state.today(),
        source_filings=sources((text(row, "filing_number") for row in rows), resolved.report),
        sections=wanted,
        fiscal_year=ref.fiscal_year,
        period=ref.period,
        period_end=ref.end_date,
        audit=built.audit,
        board=built.board,
        executives=built.executives,
        compensation=built.compensation,
        employees=built.employees,
        flags=flags,
        notes=[n for n in (resolved.note, *built.notes) if n],
    )
