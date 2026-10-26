"""Output models for audit and governance facts from periodic reports.

Amounts are integers in won. Names, positions, and audit-report text are Korean as filed;
the server maps opinions, roles, and other closed vocabularies to English.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from opendart_analysis.domain.types import ConcretePeriod
from opendart_mcp.models.common import CompanyOutput, OutputModel

GovernanceSection = Literal["audit", "board", "executives", "compensation", "employees"]
"""Sections of get_governance, each backed by its own upstream services."""

Opinion = Literal["unqualified", "qualified", "adverse", "disclaimer"]
"""External auditor's opinion type."""

Role = Literal[
    "executive_director", "outside_director", "non_executive_director", "auditor", "unregistered"
]
"""Board role of an executive."""

FlagKind = Literal["modified_opinion", "going_concern", "auditor_change"]
"""Governance red flags."""


class AuditYear(OutputModel):
    """The audit opinion for one fiscal year."""

    fiscal_year: int | None = None
    auditor: str | None = None
    opinion: Opinion | None = None
    opinion_as_filed: str | None = None
    emphasis: str | None = None
    key_audit_matters: list[str] = Field(default_factory=list)
    special_matters: str | None = None
    term_as_filed: str | None = None


class AuditFee(OutputModel):
    """Audit fees and hours, contracted and actual, for one fiscal year."""

    fiscal_year: int | None = None
    auditor: str | None = None
    contract_fee: int | None = None
    contract_hours: int | None = None
    actual_fee: int | None = None
    actual_hours: int | None = None
    scope: str | None = None


class NonAuditService(OutputModel):
    """A non-audit service contracted with the external auditor."""

    fiscal_year: int | None = None
    contracted: str | None = None
    service: str | None = None
    period: str | None = None
    fee: int | None = None
    note: str | None = None


class AuditFacts(OutputModel):
    """External auditor, opinion, fees, and any change of auditor."""

    auditor: str | None = None
    opinion: Opinion | None = None
    opinion_as_filed: str | None = None
    emphasis: str | None = None
    key_audit_matters: list[str] = Field(default_factory=list)
    prior_auditor: str | None = None
    auditor_changed_vs_prior_year: bool | None = None
    fees: list[AuditFee] = Field(default_factory=list)
    fee_scale: int | None = Field(
        default=None,
        description="Won per filed fee unit, inferred from fee per audit hour; null means fees are as filed.",
    )
    non_audit_services: list[NonAuditService] = Field(default_factory=list)
    history: list[AuditYear] | None = None


class BoardFacts(OutputModel):
    """Board size, outside directors, and changes in the period."""

    directors: int | None = None
    outside_directors: int | None = None
    outside_director_pct: float | None = None
    outside_appointed: int | None = None
    outside_dismissed: int | None = None
    outside_resigned_early: int | None = None


class Executive(OutputModel):
    """A registered or unregistered executive."""

    name: str
    position: str | None = None
    role: Role | None = None
    full_time: bool | None = None
    responsibilities: str | None = None
    term_ends: dt.date | None = None
    gender: str | None = None
    born: str | None = None
    career: str | None = None
    largest_shareholder_relation: str | None = None
    tenure: str | None = None
    role_as_filed: str | None = None


class PayGroup(OutputModel):
    """Pay for one group of people."""

    category: str | None = None
    headcount: int | None = None
    total: int | None = None
    average: int | None = None
    stock_based: int | None = None
    note: str | None = None


class PersonPay(OutputModel):
    """Pay for one person."""

    name: str
    position: str | None = None
    total: int | None = None
    not_in_total: str | None = None


class Compensation(OutputModel):
    """Director, auditor, and executive pay."""

    approved_cap: int | None = None
    paid_total: int | None = None
    headcount: int | None = None
    average: int | None = None
    by_type: list[PayGroup] = Field(default_factory=list)
    directors_over_500m: list[PersonPay] = Field(default_factory=list)
    top_paid: list[PersonPay] = Field(
        default_factory=list, description="Up to five people paid KRW 500 million or more."
    )
    unregistered_executives: PayGroup | None = None


class EmployeeGroup(OutputModel):
    """Headcount and pay for one division and gender, as filed."""

    division: str | None = None
    gender: str | None = None
    subtotal: bool | None = None
    permanent: int | None = None
    fixed_term: int | None = None
    total: int | None = None
    average_tenure_years: float | None = None
    total_salary: int | None = None
    average_salary: int | None = None


class Employees(OutputModel):
    """Workforce totals and the rows they come from."""

    total: int | None = None
    fixed_term: int | None = None
    total_salary: int | None = None
    average_salary: int | None = None
    average_tenure_years: float | None = None
    groups: list[EmployeeGroup] = Field(default_factory=list)


class GovernanceFlag(OutputModel):
    """A governance red flag."""

    kind: FlagKind
    detail: str


class GovernanceResult(CompanyOutput):
    """Audit and governance facts from one periodic report."""

    fiscal_year: int | None = None
    period: ConcretePeriod | None = None
    period_end: dt.date | None = None
    sections: list[GovernanceSection]
    audit: AuditFacts | None = None
    board: BoardFacts | None = None
    executives: list[Executive] | None = None
    compensation: Compensation | None = None
    employees: Employees | None = None
    flags: list[GovernanceFlag] = Field(default_factory=list)
