"""Output models for the debt profile: maturity ladders, the issuance record, and maturities.

Amounts are integers in won. Ladders cover debt securities only (no bank loans), as filed in
the periodic report for its period end.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from opendart_mcp.domain.types import ConcretePeriod
from opendart_mcp.models.common import CompanyOutput, OutputModel

Instrument = Literal[
    "corporate_bonds",
    "short_term_bonds",
    "commercial_paper",
    "hybrid_securities",
    "contingent_capital",
]
"""Debt security kinds with a maturity-ladder table in periodic reports."""

MaturityBucket = Literal["<=1y", "1-2y", "2-3y", "3-5y", "1-5y", ">3y", "5-10y", ">10y"]
"""Common remaining-maturity buckets; 1-5y (hybrids) and >3y (commercial paper) are as filed."""

Redeemed = Literal["yes", "no", "partly"]
"""Redemption status of an issue as filed."""


class LadderBucket(OutputModel):
    """Outstanding amount in one remaining-maturity bucket."""

    maturity_bucket: MaturityBucket
    amount: int


class FiledBucket(OutputModel):
    """One maturity column as filed, by offering type."""

    label: str
    public: int | None = None
    private: int | None = None
    total: int | None = None


class LadderEntry(OutputModel):
    """Outstanding balance of one instrument by remaining maturity."""

    instrument: Instrument
    buckets: list[LadderBucket]
    total: int | None = None
    public: int | None = None
    private: int | None = None
    issuance_limit: int | None = None
    remaining_limit: int | None = None
    filed: list[FiledBucket] | None = None


class Issuance(OutputModel):
    """One debt security in the issuance record."""

    issued: dt.date | None = None
    security: str | None = None
    method: Literal["public", "private"] | None = None
    amount: int | None = Field(default=None, description="Face value in won.")
    coupon: float | None = Field(default=None, description="Interest rate in percent.")
    rating: str | None = None
    rating_agency: str | None = None
    maturity: dt.date | None = None
    redeemed: Redeemed | None = Field(default=None, description="As of the period end.")
    issuer: str | None = Field(
        default=None, description="Set when another entity, such as a subsidiary, issued it."
    )
    underwriter: str | None = None


class DebtDerived(OutputModel):
    """Figures computed from the ladder."""

    total_debt_securities: int | None = Field(
        default=None,
        description="Sum of instrument totals, hybrids and contingent capital included.",
    )
    due_within_1y: int | None = None
    due_within_1y_pct: float | None = None


class DebtProfileResult(CompanyOutput):
    """Debt securities outstanding by maturity, and the issuance record, from one report."""

    fiscal_year: int | None = None
    period: ConcretePeriod | None = None
    period_end: dt.date | None = None
    ladder: list[LadderEntry] = Field(default_factory=list)
    issuance: list[Issuance] = Field(default_factory=list)
    derived: DebtDerived = Field(default_factory=DebtDerived)


class DebtMaturity(OutputModel):
    """A future maturity from the issuance record, for the corporate-action calendar."""

    date: dt.date
    instrument: str = Field(description="Security type as filed, such as 'Corporate Bonds'.")
    face_value: int | None = Field(
        default=None, description="Original face value in won; partly redeemed issues owe less."
    )
    filing_number: str | None = Field(
        default=None, description="Periodic report that lists the issue."
    )
    coupon: float | None = None
    redeemed: Redeemed | None = Field(default=None, description="As of the period end.")
    issuer: str | None = Field(default=None, description="Set when another entity issued it.")
