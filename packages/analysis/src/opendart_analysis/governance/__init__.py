"""Governance from periodic reports: audit, board, executives, pay, and employees.

``governance_facts`` reads the requested sections of one company's periodic report through a
caller-supplied ``FetchService`` (see ``opendart_analysis.extracts``), for the first candidate
period from ``opendart_analysis.reports.resolve_period`` that has data:

    resolved = await resolve_period(company, period="FY", fiscal_year=None, ...)
    facts = await governance_facts(
        company, resolved, sections=("audit", "board"), fetch_service=fetch, today=today
    )

Amounts are integers in won as filed; audit fees, filed without a unit, are converted with the
unit inferred from the fee per audit hour (``fee_scale``). Names, titles, and audit-report text
stay Korean as filed; opinions, roles, and flags are English. Values keep every field the report
provides. Modules: ``values`` (result types), ``audit``, ``people`` (board, executives, and
employees), ``pay``, and ``fetch`` (the workflow). Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.governance.audit import (
    audit_facts,
    audit_flags,
    changed,
    fee_scale,
    key_matters,
    opinion,
    opinion_rows,
    same_auditor,
    scale_note,
)
from opendart_analysis.governance.fetch import (
    DEFAULT_SECTIONS,
    SECTIONS,
    SECTION_SERVICES,
    VERSIONED,
    GovernanceFacts,
    fetch_tables,
    governance_facts,
    prior_auditor,
)
from opendart_analysis.governance.pay import PayTables, compensation, newest, people
from opendart_analysis.governance.people import (
    board,
    born,
    bullets,
    employees,
    executive,
    executives,
    full_time,
    gender,
    headline,
    is_subtotal,
    role,
)
from opendart_analysis.governance.values import (
    AuditFacts,
    AuditFee,
    AuditYear,
    BoardFacts,
    Compensation,
    EmployeeGroup,
    Employees,
    Executive,
    FlagKind,
    GovernanceFlag,
    GovernanceSection,
    NonAuditService,
    Opinion,
    PayGroup,
    PersonPay,
    Role,
)

__all__ = [
    "DEFAULT_SECTIONS",
    "SECTIONS",
    "SECTION_SERVICES",
    "VERSIONED",
    "AuditFacts",
    "AuditFee",
    "AuditYear",
    "BoardFacts",
    "Compensation",
    "EmployeeGroup",
    "Employees",
    "Executive",
    "FlagKind",
    "GovernanceFacts",
    "GovernanceFlag",
    "GovernanceSection",
    "NonAuditService",
    "Opinion",
    "PayGroup",
    "PayTables",
    "PersonPay",
    "Role",
    "audit_facts",
    "audit_flags",
    "board",
    "born",
    "bullets",
    "changed",
    "compensation",
    "employees",
    "executive",
    "executives",
    "fee_scale",
    "fetch_tables",
    "full_time",
    "gender",
    "governance_facts",
    "headline",
    "is_subtotal",
    "key_matters",
    "newest",
    "opinion",
    "opinion_rows",
    "people",
    "prior_auditor",
    "role",
    "same_auditor",
    "scale_note",
]
