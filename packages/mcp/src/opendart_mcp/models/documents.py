"""Output models for read_filing and the filing resources.

Results are compact versions of the document layer's models, because hosts such as Claude
Code hand the structured result to the model and output schemas count toward the tool
definition budget. Small document-layer models (aliases, amendments, search hits) are
embedded as they are.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from opendart_analysis.documents.models import (
    Amendment,
    DocumentFormat,
    SearchHit,
    SuggestedSection,
)
from opendart_mcp.models.common import OutputModel, ToolOutput

FilingMode = Literal["outline", "read", "search"]
"""What read_filing returns: the document map, one page of text, or search hits."""


class FilingInfo(OutputModel):
    """The filing a read_filing result comes from."""

    filing_number: str
    form_code: str | None = None
    form_name: str | None = Field(default=None, description="English form name, when known.")
    form_name_ko: str | None = None
    company: str | None = Field(default=None, description="Company name as written in the filing.")
    corp_code: str | None = None
    filed: date | None = None
    is_amendment: bool
    format: DocumentFormat = Field(
        description="dart_xml (FSS filing) or krx_html (KRX disclosure)."
    )
    language: Literal["ko"] = Field(
        default="ko", description="Body text language; translate it. Headings use English labels."
    )
    dart_url: str


class DocumentEntry(OutputModel):
    """A document in the filing archive: the main document or an attachment."""

    key: str = Field(description="Value for `document`.")
    form_code: str | None = None
    name: str | None = Field(default=None, description="English form name, when known.")
    name_ko: str | None = None
    chars: int = Field(description="Rendered characters.")


class OutlineSection(OutputModel):
    """An outline entry; its id is a value for `section`."""

    id: str
    level: int
    title_en: str | None = None
    title_ko: str
    chars: int = Field(description="Rendered characters, subsections included.")
    tables: int
    placeholder: bool | None = Field(
        default=None, description="True when the section only says the item is omitted."
    )
    image_only: bool | None = Field(
        default=None, description="True when the content is images the archive omits."
    )


class FilingOutline(OutputModel):
    """Map of one document, without body text."""

    documents: list[DocumentEntry]
    sections: list[OutlineSection]
    suggested_sections: list[SuggestedSection] = Field(
        default_factory=list, description="Section aliases present (periodic reports)."
    )
    amendment: Amendment | None = Field(default=None, description="What an amended filing changed.")


class FilingPage(OutputModel):
    """One page of rendered Markdown."""

    section: OutlineSection | None = Field(
        default=None, description="Section read; null for the whole document."
    )
    offset: int
    next_offset: int | None = Field(
        default=None, description="Offset of the next page; null on the last page."
    )
    total_chars: int
    truncated: bool = Field(description="True when more text follows this page.")
    content: str


class FilingHits(OutputModel):
    """Passages matching a query."""

    query: str
    section: str | None = Field(default=None, description="Section searched; null for all.")
    hits: list[SearchHit]
    total_hits: int


class ReadFilingResult(ToolOutput):
    """An outline, a page of text, or search hits from one filing."""

    filing: FilingInfo
    mode: FilingMode
    document: str = Field(description="Key of the document used.")
    outline: FilingOutline | None = None
    page: FilingPage | None = None
    search: FilingHits | None = None
