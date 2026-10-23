"""Output models for get_ownership: control snapshot, control changes, and holding reports.

Percentages are floats in percent units (19.84 means 19.84%) of the issued shares of the
holding's class, as filed; share counts are integers.
"""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from opendart_mcp.domain.types import ConcretePeriod
from opendart_mcp.models.common import CompanyOutput, OutputModel


class Holder(OutputModel):
    """One holding of the largest shareholder or a related party."""

    name: str
    relation: str | None = Field(default=None, description="Relation to the largest shareholder.")
    share_class: str
    shares: int | None = Field(default=None, description="Shares at the period end.")
    pct_begin: float | None = None
    pct_end: float | None = None
    shares_begin: int | None = None
    note: str | None = None


class Minority(OutputModel):
    """Minority (small) shareholders and their combined holding."""

    holders: int | None = None
    total_holders: int | None = None
    holder_pct: float | None = Field(default=None, description="Share of all shareholders.")
    shares: int | None = None
    share_pct: float | None = Field(default=None, description="Share of all issued shares.")
    total_shares: int | None = None
    as_of: dt.date | None = None


class OwnershipSnapshot(OutputModel):
    """Control at the period end, for the voting share class."""

    share_class: str = Field(description="Class the percentages, counts, and float refer to.")
    largest_shareholder: str | None = None
    largest_shareholder_group: list[Holder] = Field(default_factory=list)
    group_members: int = Field(default=0, description="Distinct holders in the group.")
    controlling_shares: int | None = None
    controlling_pct: float | None = None
    controlling_pct_begin: float | None = None
    minority: Minority | None = None
    shares_issued: int | None = Field(default=None, description="Treasury shares included.")
    treasury_shares: int | None = None
    shares_outstanding: int | None = Field(default=None, description="Issued minus treasury.")
    free_float_estimate_pct: float | None = Field(
        default=None, description="Estimate: issued minus group and treasury, over issued."
    )


class ControlChange(OutputModel):
    """A change of the largest shareholder."""

    date: dt.date | None = None
    new_largest_shareholder: str | None = None
    shares: int | None = None
    pct: float | None = None
    cause: str | None = None
    note: str | None = None


class MajorHolderReport(OutputModel):
    """A 5% (significant holding) report."""

    filed: dt.date | None = None
    filing_number: str
    reporter: str | None = None
    report_type: str | None = None
    shares: int | None = None
    change_in_shares: int | None = None
    pct: float | None = None
    change_in_pct: float | None = Field(default=None, description="Percentage points.")
    reason: str | None = None
    contract_shares: int | None = Field(default=None, description="Shares under major contracts.")
    contract_pct: float | None = None


class InsiderReport(OutputModel):
    """An ownership report of an executive or major shareholder."""

    filed: dt.date | None = None
    filing_number: str
    reporter: str | None = None
    position: str | None = None
    is_registered_officer: bool | None = None
    major_shareholder: str | None = None
    shares: int | None = None
    change: int | None = None
    pct: float | None = None
    change_pct: float | None = Field(default=None, description="Percentage points.")


class ReportActivity(OutputModel):
    """Counts over every report filed in the activity window, not only those shown."""

    reports: int
    shown: int
    increases: int
    decreases: int
    net_change: int = Field(description="Sum of reported share changes.")


class OwnershipResult(CompanyOutput):
    """Control snapshot from one periodic report plus holding reports in a date window."""

    fiscal_year: int | None = None
    period: ConcretePeriod | None = None
    period_end: dt.date | None = None
    snapshot: OwnershipSnapshot | None = None
    control_changes: list[ControlChange] = Field(default_factory=list)
    activity_since: dt.date
    activity_until: dt.date
    major_holder_reports: list[MajorHolderReport] = Field(default_factory=list)
    major_holder_activity: ReportActivity | None = Field(
        default=None, description="Null while the reports are still downloading."
    )
    insider_reports: list[InsiderReport] = Field(default_factory=list)
    insider_activity: ReportActivity | None = Field(
        default=None, description="Null while the reports are still downloading."
    )
