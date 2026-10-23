"""Fields shared by every tool result: identity, provenance, notes, and paging.

Every company-scoped result names the resolved company, the server date in KST, the
filings it was built from, and notes about fallbacks, estimates, and coverage gaps.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from opendart_mcp.domain.identifiers import dart_viewer_url, filing_date
from opendart_mcp.domain.types import Market


class OutputModel(BaseModel):
    """Base for output models: strict field names and JSON-friendly serialization."""

    model_config = ConfigDict(extra="forbid", ser_json_inf_nan="null")


class CompanyRef(OutputModel):
    """A company resolved from a name, stock code, or DART corporation code."""

    name: str = Field(description="English company name when known, else the Korean name.")
    korean_name: str | None = Field(default=None, description="Formal Korean name.")
    corp_code: str = Field(description="8-digit DART corporation code.")
    stock_code: str | None = Field(
        default=None, description="6-character KRX stock code; null for unlisted companies."
    )
    market: Market | None = Field(
        default=None, description="Listing market; null when not yet known."
    )


class SourceFiling(OutputModel):
    """A filing a result was built from; its number is the handle for read_filing."""

    filing_number: str = Field(description="14-digit filing (receipt) number.")
    title: str | None = Field(default=None, description="Report title as filed.")
    filed: date | None = Field(default=None, description="Filing date.")
    dart_url: str = Field(description="DART viewer link for citation.")

    @classmethod
    def of(cls, filing_number: str, title: str | None = None) -> SourceFiling:
        """Describe a filing, deriving its date and viewer link from the number.

        Args:
            filing_number (str): 14-digit filing number.
            title (str | None): Report title, when known.

        Returns:
            SourceFiling: Provenance entry.
        """
        return cls(
            filing_number=filing_number,
            title=title,
            filed=filing_date(filing_number),
            dart_url=dart_viewer_url(filing_number),
        )


class NextCall(OutputModel):
    """The exact call that fetches the next page of a result."""

    tool: str = Field(description="Tool to call.")
    arguments: dict[str, JsonValue] = Field(description="Arguments for that call.")


class Pagination(OutputModel):
    """Bounded result paging."""

    total: int | None = Field(default=None, description="Total matching items, when known.")
    page: int = Field(description="1-based page number of this result.")
    limit: int = Field(description="Maximum items per page.")
    has_more: bool = Field(description="Whether another page exists.")
    next_call: NextCall | None = Field(default=None, description="Call for the next page.")


class ToolOutput(OutputModel):
    """Provenance fields present on every tool result."""

    as_of: date = Field(description="Server date (KST) when the result was produced.")
    source_filings: list[SourceFiling] = Field(
        default_factory=list, description="Filings the result was built from."
    )
    notes: list[str] = Field(
        default_factory=list, description="Fallbacks, estimates, and coverage gaps."
    )


class CompanyOutput(ToolOutput):
    """A result about one company."""

    company: CompanyRef = Field(description="The resolved company.")
