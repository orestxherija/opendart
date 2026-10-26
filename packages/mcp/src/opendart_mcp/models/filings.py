"""Output models for the filing index: search_filings and the company filings resource."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from opendart_analysis.domain.categories import FilingCategory
from opendart_mcp.models.common import CompanyRef, OutputModel, Pagination, ToolOutput


class FilingItem(OutputModel):
    """One filing in the index."""

    filing_number: str = Field(description="14-digit handle for read_filing and citations.")
    filed: date | None = None
    company: CompanyRef | None = Field(
        default=None, description="Company the filing concerns; omitted when the search names it."
    )
    title: str = Field(description="Report title as filed (English API), whitespace collapsed.")
    submitter: str | None = None
    category: FilingCategory | None = Field(
        default=None, description="Category searched, or inferred from the title; null if unknown."
    )
    is_amendment: bool = Field(description="Re-submits an earlier filing (bracketed title marker).")
    corrected_later: bool | None = Field(
        default=None, description="True when a later filing corrects this one."
    )
    withdrawn: bool | None = Field(
        default=None, description="True when the filing was withdrawn or deemed withdrawn."
    )
    dart_url: str


class SearchFilingsResult(ToolOutput):
    """Filings matching a search, newest first."""

    company: CompanyRef | None = Field(
        default=None, description="Company searched; null for market-wide searches."
    )
    since: date
    until: date
    filings: list[FilingItem]
    pagination: Pagination
