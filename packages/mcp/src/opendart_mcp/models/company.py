"""Output models for company identity: directory matches and company profiles."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from opendart_analysis.domain.types import ConcretePeriod, Market
from opendart_mcp.models.common import CompanyOutput, OutputModel, ToolOutput

MatchKind = Literal["code", "exact", "prefix", "token", "fuzzy"]
PeriodicKind = Literal["annual", "semiannual", "quarterly"]


class CompanyMatch(OutputModel):
    """A company matching a search."""

    corp_code: str
    name: str = Field(description="English name when known, else the Korean name.")
    korean_name: str
    stock_code: str | None = None
    market: Market | None = Field(
        default=None, description="Set when known or requested; null otherwise."
    )
    listed: bool = Field(description="Has a KRX stock code (delisted companies keep theirs).")
    last_modified: date | None = None
    match: MatchKind


class FindCompanyResult(ToolOutput):
    """Directory matches for a company search."""

    query: str
    matches: list[CompanyMatch]
    best_match: CompanyMatch | None = Field(
        default=None, description="Set only when one candidate clearly dominates."
    )


class PeriodicReportRef(OutputModel):
    """The latest periodic report, which defines period="latest"."""

    kind: PeriodicKind
    fiscal_year: int
    period: ConcretePeriod
    period_end: date | None = None
    filed: date | None = None
    filing_number: str
    title: str


class CompanyProfile(OutputModel):
    """Reference facts from the company overview."""

    stock_name: str | None = None
    ceo: str | None = None
    industry_code: str | None = None
    fiscal_year_end_month: int
    established: date | None = None
    address: str | None = None
    website: str | None = None
    ir_url: str | None = None
    phone: str | None = None
    fax: str | None = None
    corporate_registration_number: str | None = None
    business_registration_number: str | None = None


class CompanyProfileResult(CompanyOutput):
    """Identity, reference facts, and the latest periodic report of one company."""

    profile: CompanyProfile
    latest_periodic_report: PeriodicReportRef | None = None
