"""Governance values read from one periodic report: audit, board, executives, pay, and staff.

Amounts are integers in won, except audit fees whose unit could not be inferred (``fee_scale``
is None), which stay as filed. Names, positions, and audit-report text stay Korean as filed;
opinions, roles, and other closed vocabularies are English. Every value keeps every field the
report provides, so callers choose what to show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import datetime as dt

type GovernanceSection = Literal["audit", "board", "executives", "compensation", "employees"]
"""Sections of a governance read, each backed by its own periodic-report services."""

type Opinion = Literal["unqualified", "qualified", "adverse", "disclaimer"]
"""External auditor's opinion type."""

type Role = Literal[
    "executive_director", "outside_director", "non_executive_director", "auditor", "unregistered"
]
"""Board role of an executive."""

type FlagKind = Literal["modified_opinion", "going_concern", "auditor_change"]
"""Governance red flags."""


@dataclass(frozen=True, slots=True)
class AuditYear:
    """The audit opinion for one fiscal year, as one row of the opinion table.

    Attributes:
        fiscal_year (int | None): Fiscal year the row covers.
        auditor (str | None): Audit firm as filed.
        opinion (Opinion | None): Opinion type, or None when unrecognized.
        opinion_as_filed (str | None): Opinion text as filed, such as 적정의견.
        emphasis (str | None): Emphasis-of-matter paragraph.
        key_audit_matters (tuple[str, ...]): Key audit matters, one per item.
        special_matters (str | None): Other matters in the audit report.
        term_as_filed (str | None): Term label as filed, such as ``제57기 (당기)``.
    """

    fiscal_year: int | None = None
    auditor: str | None = None
    opinion: Opinion | None = None
    opinion_as_filed: str | None = None
    emphasis: str | None = None
    key_audit_matters: tuple[str, ...] = ()
    special_matters: str | None = None
    term_as_filed: str | None = None


@dataclass(frozen=True, slots=True)
class AuditFee:
    """Audit fees and hours, contracted and actual, for one fiscal year.

    Attributes:
        fiscal_year (int | None): Fiscal year.
        auditor (str | None): Audit firm as filed.
        contract_fee (int | None): Contracted fee.
        contract_hours (int | None): Contracted hours.
        actual_fee (int | None): Fee actually charged.
        actual_hours (int | None): Hours actually worked.
        scope (str | None): Work covered, as filed.
    """

    fiscal_year: int | None = None
    auditor: str | None = None
    contract_fee: int | None = None
    contract_hours: int | None = None
    actual_fee: int | None = None
    actual_hours: int | None = None
    scope: str | None = None


@dataclass(frozen=True, slots=True)
class NonAuditService:
    """A non-audit service contracted with the external auditor.

    Attributes:
        fiscal_year (int | None): Fiscal year.
        contracted (str | None): Contract date as filed.
        service (str | None): Service description.
        period (str | None): Service period as filed.
        fee (int | None): Fee.
        note (str | None): Remarks as filed.
    """

    fiscal_year: int | None = None
    contracted: str | None = None
    service: str | None = None
    period: str | None = None
    fee: int | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class AuditFacts:
    """External auditor, opinion, fees, and any change of auditor.

    Attributes:
        auditor (str | None): Current auditor.
        opinion (Opinion | None): Most severe current-year opinion.
        opinion_as_filed (str | None): That opinion as filed.
        emphasis (str | None): First current-year emphasis of matter.
        key_audit_matters (tuple[str, ...]): First current-year key audit matters.
        prior_auditor (str | None): Prior fiscal year's auditor, when known.
        auditor_changed_vs_prior_year (bool | None): Whether the auditor changed; None when
            either auditor is unknown.
        fees (tuple[AuditFee, ...]): Fees by fiscal year, newest first.
        fee_scale (int | None): Won per filed fee unit, inferred from the fee per audit hour;
            None means fees are as filed.
        non_audit_services (tuple[NonAuditService, ...]): Non-audit services, every fiscal
            year the table covers.
        history (tuple[AuditYear, ...]): Distinct opinion rows, newest fiscal year first.
    """

    auditor: str | None = None
    opinion: Opinion | None = None
    opinion_as_filed: str | None = None
    emphasis: str | None = None
    key_audit_matters: tuple[str, ...] = ()
    prior_auditor: str | None = None
    auditor_changed_vs_prior_year: bool | None = None
    fees: tuple[AuditFee, ...] = ()
    fee_scale: int | None = None
    non_audit_services: tuple[NonAuditService, ...] = ()
    history: tuple[AuditYear, ...] = ()


@dataclass(frozen=True, slots=True)
class BoardFacts:
    """Board size, outside directors, and outside-director changes in the period.

    Attributes:
        directors (int | None): Directors on the board.
        outside_directors (int | None): Outside directors.
        outside_director_pct (float | None): Outside directors as a percentage of the board,
            one decimal.
        outside_appointed (int | None): Outside directors appointed.
        outside_dismissed (int | None): Outside directors dismissed.
        outside_resigned_early (int | None): Outside directors who resigned early.
    """

    directors: int | None = None
    outside_directors: int | None = None
    outside_director_pct: float | None = None
    outside_appointed: int | None = None
    outside_dismissed: int | None = None
    outside_resigned_early: int | None = None


@dataclass(frozen=True, slots=True)
class Executive:
    """A registered or unregistered executive.

    Attributes:
        name (str): Name as filed.
        position (str | None): Title as filed.
        role (Role | None): Board role, or None when unrecognized.
        full_time (bool | None): Full-time status, when stated.
        responsibilities (str | None): Duties, separated by semicolons.
        term_ends (dt.date | None): End of the current term.
        gender (str | None): male, female, or as filed.
        born (str | None): Birth year and month, YYYY-MM.
        career (str | None): Main career, separated by semicolons.
        largest_shareholder_relation (str | None): Relation to the largest shareholder.
        tenure (str | None): Time in office as filed.
        role_as_filed (str | None): Board role as filed.
    """

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


@dataclass(frozen=True, slots=True)
class PayGroup:
    """Pay for one group of people.

    Attributes:
        category (str | None): Group as filed.
        headcount (int | None): People in the group.
        total (int | None): Total pay.
        average (int | None): Average pay per person.
        stock_based (int | None): Stock-based pay.
        note (str | None): Remarks as filed.
    """

    category: str | None = None
    headcount: int | None = None
    total: int | None = None
    average: int | None = None
    stock_based: int | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class PersonPay:
    """Pay for one person.

    Attributes:
        name (str): Name as filed.
        position (str | None): Title as filed.
        total (int | None): Total pay.
        not_in_total (str | None): Pay outside the total, as filed.
    """

    name: str
    position: str | None = None
    total: int | None = None
    not_in_total: str | None = None


@dataclass(frozen=True, slots=True)
class Compensation:
    """Director, auditor, and executive pay.

    Attributes:
        approved_cap (int | None): Shareholder-approved pay ceiling.
        paid_total (int | None): Total paid to all directors and auditors.
        headcount (int | None): Directors and auditors paid.
        average (int | None): Average pay per director or auditor.
        by_type (tuple[PayGroup, ...]): Pay by director category, without totals.
        directors_over_500m (tuple[PersonPay, ...]): Directors and auditors paid KRW 500
            million or more, highest first.
        top_paid (tuple[PersonPay, ...]): Up to five people paid KRW 500 million or more,
            highest first.
        unregistered_executives (PayGroup | None): Pay of unregistered executives.
    """

    approved_cap: int | None = None
    paid_total: int | None = None
    headcount: int | None = None
    average: int | None = None
    by_type: tuple[PayGroup, ...] = ()
    directors_over_500m: tuple[PersonPay, ...] = ()
    top_paid: tuple[PersonPay, ...] = ()
    unregistered_executives: PayGroup | None = None


@dataclass(frozen=True, slots=True)
class EmployeeGroup:
    """Headcount and pay for one division and gender, as filed.

    Attributes:
        division (str | None): Business division as filed.
        gender (str | None): male, female, as filed, or None for totals.
        subtotal (bool | None): True for total and subtotal rows.
        permanent (int | None): Permanent employees.
        fixed_term (int | None): Fixed-term employees.
        total (int | None): All employees.
        average_tenure_years (float | None): Average tenure in years.
        total_salary (int | None): Total salary for the year.
        average_salary (int | None): Average salary.
    """

    division: str | None = None
    gender: str | None = None
    subtotal: bool | None = None
    permanent: int | None = None
    fixed_term: int | None = None
    total: int | None = None
    average_tenure_years: float | None = None
    total_salary: int | None = None
    average_salary: int | None = None


@dataclass(frozen=True, slots=True)
class Employees:
    """Workforce totals and every row of the workforce table.

    Totals add up the headline rows (``people.headline``): a grand-total row, else subtotal
    rows such as one per gender, else every row.

    Attributes:
        total (int | None): All employees.
        fixed_term (int | None): Fixed-term employees.
        total_salary (int | None): Total salary for the year.
        average_salary (int | None): Average salary, weighted by implied average headcount.
        average_tenure_years (float | None): Headcount-weighted tenure, one decimal.
        groups (tuple[EmployeeGroup, ...]): Every row with figures, as filed.
    """

    total: int | None = None
    fixed_term: int | None = None
    total_salary: int | None = None
    average_salary: int | None = None
    average_tenure_years: float | None = None
    groups: tuple[EmployeeGroup, ...] = ()


@dataclass(frozen=True, slots=True)
class GovernanceFlag:
    """A governance red flag.

    Attributes:
        kind (FlagKind): What the flag marks.
        detail (str): One sentence describing it.
    """

    kind: FlagKind
    detail: str
