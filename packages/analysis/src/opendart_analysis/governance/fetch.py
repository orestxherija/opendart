"""Read governance facts from one periodic report through a caller-supplied ``FetchService``.

Each section has its own periodic-report services, and only the requested sections are
fetched, all at once for one period. The individual-pay services prefer Ver 2.0 and fall back
to Ver 1.0 when Ver 2.0 has no data. Flags come from the audit section: a modified opinion,
going-concern language, and an auditor change from the prior fiscal year, which costs one
extra call when the report does not list the prior year's auditor.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.periods import FIRST_FISCAL_YEAR, PeriodRef
from opendart_analysis.extracts import (
    fetch_records,
    fetch_response,
    gather_all,
    probe_attempts,
    records,
    sources,
    text,
)
from opendart_analysis.governance.audit import audit_facts, audit_flags, changed, opinion_rows
from opendart_analysis.governance.pay import PayTables, compensation
from opendart_analysis.governance.people import board, employees, executives
from opendart_analysis.reports import first_available

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from opendart_analysis.extracts import FilingSource
    from opendart_analysis.governance.values import (
        AuditFacts,
        BoardFacts,
        Compensation,
        Employees,
        Executive,
        GovernanceFlag,
        GovernanceSection,
    )
    from opendart_analysis.reports import FiscalCompany, ResolvedPeriod
    from opendart_analysis.upstream import FetchService

    type Tables = Mapping[str, Sequence[object] | None]

SECTIONS: Final[tuple[GovernanceSection, ...]] = (
    "audit",
    "board",
    "executives",
    "compensation",
    "employees",
)
"""Every section, in reading order."""

DEFAULT_SECTIONS: Final[tuple[GovernanceSection, ...]] = ("audit", "board")
"""Sections read when none are named."""

OPINIONS: Final = "accnut_adtor_nm_nd_adt_opinion"
FEES: Final = "adt_servc_cncls_sttus"
NON_AUDIT: Final = "accnut_adtor_non_adt_servc_cncls_sttus"
BOARD: Final = "outcmpny_drctr_nd_change_sttus"
EXECUTIVES: Final = "exctv_sttus"
EMPLOYEES: Final = "emp_sttus"
DIRECTORS_PAY: Final = "directors_over_500m"
TOP_PAY: Final = "top_paid"

SECTION_SERVICES: Final[Mapping[GovernanceSection, tuple[str, ...]]] = {
    "audit": (OPINIONS, FEES, NON_AUDIT),
    "board": (BOARD,),
    "executives": (EXECUTIVES,),
    "compensation": (
        "drctr_adt_all_mendng_sttus_gmtsck_confm_amount",
        "hmv_audit_all_sttus",
        "drctr_adt_all_mendng_sttus_mendng_pymntamt_ty_cl",
        "unrst_exctv_mendng_sttus",
    ),
    "employees": (EMPLOYEES,),
}
"""Periodic-report services per section, by SDK method name; pay also reads ``VERSIONED``."""

VERSIONED: Final = (
    (DIRECTORS_PAY, "hmv_audit_indvdl_by_sttus_v2", "hmv_audit_indvdl_by_sttus"),
    (TOP_PAY, "indvdl_by_pay_v2", "indvdl_by_pay"),
)
"""Individual pay: table key, preferred Ver 2.0 service, and its Ver 1.0 fallback."""


@dataclass(frozen=True, slots=True)
class GovernanceFacts:
    """Governance facts from one periodic report.

    A section is None when it was not requested or the report has no data for it.

    Attributes:
        ref (PeriodRef): Period of the report that had data.
        sections (tuple[GovernanceSection, ...]): Requested sections, without duplicates.
        audit (AuditFacts | None): Audit section.
        board (BoardFacts | None): Board section.
        executives (tuple[Executive, ...] | None): Every named executive, registered or not.
        compensation (Compensation | None): Pay section.
        employees (Employees | None): Workforce section.
        flags (tuple[GovernanceFlag, ...]): Flags from the audit section; empty when audit
            was not requested.
        sources (tuple[FilingSource, ...]): Filings the records came from, in order of first
            appearance, the prior-year opinion lookup last.
    """

    ref: PeriodRef
    sections: tuple[GovernanceSection, ...]
    audit: AuditFacts | None = None
    board: BoardFacts | None = None
    executives: tuple[Executive, ...] | None = None
    compensation: Compensation | None = None
    employees: Employees | None = None
    flags: tuple[GovernanceFlag, ...] = ()
    sources: tuple[FilingSource, ...] = ()


def requested(sections: Sequence[GovernanceSection]) -> tuple[GovernanceSection, ...]:
    """Check requested sections and drop duplicates, keeping the first of each.

    Args:
        sections (Sequence[GovernanceSection]): Requested sections.

    Returns:
        tuple[GovernanceSection, ...]: Sections in request order.

    Raises:
        ValueError: No section is named, or one is not in ``SECTIONS``.
    """
    wanted = tuple(dict.fromkeys(sections))
    unknown = [section for section in wanted if section not in SECTION_SERVICES]
    if not wanted or unknown:
        message = f"sections must name 1 to {len(SECTIONS)} of {", ".join(SECTIONS)}; got {list(sections)}."
        raise ValueError(message)
    return wanted


async def fetch_tables(
    company: FiscalCompany,
    ref: PeriodRef,
    *,
    sections: Sequence[GovernanceSection],
    fetch_service: FetchService,
    today: date,
) -> dict[str, list[object] | None] | None:
    """Fetch the services the requested sections need, concurrently, for one period.

    Args:
        company (FiscalCompany): Company.
        ref (PeriodRef): Fiscal year and period.
        sections (Sequence[GovernanceSection]): Requested sections.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST, which sets the period's volatility.

    Returns:
        dict[str, list[object] | None] | None: Records by service name (and by
            ``DIRECTORS_PAY`` and ``TOP_PAY`` for individual pay), or None when no service has
            data.
    """

    async def table(service: str) -> list[object] | None:
        """Fetch one service's records.

        Args:
            service (str): SDK method name.

        Returns:
            list[object] | None: Records, or None for no data.
        """
        return await fetch_records(
            service, company=company, ref=ref, fetch_service=fetch_service, today=today
        )

    async def versioned(newer: str, older: str) -> list[object] | None:
        """Fetch individual pay from Ver 2.0, or from Ver 1.0 when Ver 2.0 has none.

        Args:
            newer (str): Ver 2.0 service, whose people sit under ``group``.
            older (str): Ver 1.0 service.

        Returns:
            list[object] | None: People, or None when neither version has data.
        """
        response = await fetch_response(
            newer, company=company, ref=ref, fetch_service=fetch_service, today=today
        )
        found = records(response, "group") if response is not None else None
        return found or await table(older)

    names = [name for section in sections for name in SECTION_SERVICES[section]]
    calls = [table(name) for name in names]
    if "compensation" in sections:
        names += [key for key, *_ in VERSIONED]
        calls += [versioned(newer, older) for _, newer, older in VERSIONED]
    found = await gather_all(calls)
    if all(rows is None for rows in found):
        return None
    return dict(zip(names, found, strict=True))


def _read_sections(
    tables: Tables, ref: PeriodRef, sections: tuple[GovernanceSection, ...]
) -> GovernanceFacts:
    """Build the requested sections from one report's tables, without flags or sources.

    Args:
        tables (Tables): Records by service, from ``fetch_tables``.
        ref (PeriodRef): Period of the report.
        sections (tuple[GovernanceSection, ...]): Requested sections.

    Returns:
        GovernanceFacts: Requested sections; the others are None.
    """

    def rows(service: str) -> Sequence[object]:
        """Return a service's records, empty when it had no data.

        Args:
            service (str): Service name or individual-pay key.

        Returns:
            Sequence[object]: Records.
        """
        return tables.get(service) or ()

    year = ref.fiscal_year
    approved, paid, by_type, unregistered = SECTION_SERVICES["compensation"]
    pay = PayTables(
        approved=rows(approved),
        paid=rows(paid),
        by_type=rows(by_type),
        directors=rows(DIRECTORS_PAY),
        top=rows(TOP_PAY),
        unregistered=rows(unregistered),
    )
    return GovernanceFacts(
        ref,
        sections,
        audit=audit_facts(
            opinion_rows(rows(OPINIONS), year), rows(FEES), rows(NON_AUDIT), fiscal_year=year
        )
        if "audit" in sections
        else None,
        board=board(rows(BOARD)) if "board" in sections else None,
        executives=(tuple(executives(rows(EXECUTIVES))) or None)
        if "executives" in sections
        else None,
        compensation=compensation(pay) if "compensation" in sections else None,
        employees=employees(rows(EMPLOYEES)) if "employees" in sections else None,
    )


async def prior_auditor(
    company: FiscalCompany,
    audit: AuditFacts,
    ref: PeriodRef,
    *,
    fetch_service: FetchService,
    today: date,
) -> tuple[AuditFacts, list[object]]:
    """Look up last fiscal year's auditor when the report does not list it.

    Args:
        company (FiscalCompany): Company.
        audit (AuditFacts): Audit facts of the report.
        ref (PeriodRef): Period of the report.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        tuple[AuditFacts, list[object]]: Audit facts with the prior auditor and change, and
            the records of the extra call, for provenance; unchanged and empty when the call
            is not needed or the prior year predates OpenDART's periodic data.
    """
    year = ref.fiscal_year - 1
    if audit.auditor is None or audit.prior_auditor or year < FIRST_FISCAL_YEAR:
        return audit, []
    found = (
        await fetch_records(
            OPINIONS,
            company=company,
            ref=PeriodRef(year, "FY"),
            fetch_service=fetch_service,
            today=today,
        )
        or []
    )
    rows = [row for row in opinion_rows(found, year) if row.fiscal_year == year and row.auditor]
    prior = rows[0].auditor if rows else None
    updated = dataclasses.replace(
        audit, prior_auditor=prior, auditor_changed_vs_prior_year=changed(audit.auditor, prior)
    )
    return updated, found


async def governance_facts(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    sections: Sequence[GovernanceSection] = DEFAULT_SECTIONS,
    fetch_service: FetchService,
    today: date,
) -> GovernanceFacts | None:
    """Read the requested governance sections from the newest candidate report with data.

    Probes at most ``probe_attempts(resolved)`` candidate periods (three or fewer); each probe
    calls the requested sections' services at once, plus a Ver 1.0 fallback for each
    individual-pay service without Ver 2.0 data. With the audit section, one more call reads
    the prior annual report's opinion table when the report does not name last year's auditor.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        sections (Sequence[GovernanceSection]): Sections to read; duplicates are ignored.
        fetch_service (FetchService): Service calls, keyed by SDK method name; failures
            propagate unchanged.
        today (date): Today in KST, which sets each period's volatility.

    Returns:
        GovernanceFacts | None: Facts from the first candidate period with any table, or None
            when no candidate has one.

    Raises:
        ValueError: ``sections`` is empty or names an unknown section.
    """
    wanted = requested(sections)
    found = await first_available(
        resolved,
        lambda ref: fetch_tables(
            company, ref, sections=wanted, fetch_service=fetch_service, today=today
        ),
        attempts=probe_attempts(resolved),
    )
    if found is None:
        return None
    ref, tables = found
    facts = _read_sections(tables, ref, wanted)
    audit = facts.audit
    extra: list[object] = []
    if audit is not None:
        audit, extra = await prior_auditor(
            company, audit, ref, fetch_service=fetch_service, today=today
        )
    flags = (
        audit_flags(audit, audit.history, fiscal_year=ref.fiscal_year, label=ref.label)
        if audit is not None
        else []
    )
    rows = [*(row for batch in tables.values() for row in batch or ()), *extra]
    numbers = (text(row, "filing_number") for row in rows)
    return dataclasses.replace(
        facts, audit=audit, flags=tuple(flags), sources=tuple(sources(numbers, resolved.report))
    )
