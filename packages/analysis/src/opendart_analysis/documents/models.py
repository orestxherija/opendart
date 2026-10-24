"""Pydantic models returned by the filing-document layer.

MCP tool and resource output models embed these, so their fields and descriptions are part of
the MCP wire contract. Offsets and character counts refer to the rendered Markdown in the
requested label language.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LabelMode = Literal["english", "korean", "both"]
"""Label language: ``english`` uses the filing's ``ENG`` labels with a Korean fallback,
``korean`` keeps the original, and ``both`` renders ``English (Korean)``."""

DocumentFormat = Literal["dart_xml", "krx_html"]
"""Member format: FSS DART XML or a KRX exchange-disclosure HTML page."""

TableLayout = Literal["grid", "form"]
"""How a table was rendered: a Markdown table, or ``label: value`` lines."""


class DocumentModel(BaseModel):
    """Base for document-layer results: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class DocumentInfo(DocumentModel):
    """One document in the filing archive: the main document or an attachment."""

    key: str = Field(
        description="Value for `document`: main, audit_report, consolidated_audit_report, or the attachment's form code."
    )
    form_code: str | None = Field(default=None, description="DART form code, when known.")
    name_en: str | None = Field(default=None, description="English form name, when known.")
    name_ko: str | None = Field(default=None, description="Korean form name.")
    chars: int = Field(description="Rendered characters with English labels.")
    member: str = Field(description="Archive member name.")
    size_bytes: int = Field(description="Expanded member size in bytes.")
    rendered: bool = Field(
        default=True, description="False for members that are not DART XML or KRX HTML."
    )


class SectionInfo(DocumentModel):
    """One outline entry."""

    id: str = Field(
        description="Section ID for `section`: the filing's section code (D-0-3-3-0), s{toc id}, or an ordinal path such as p2.1."
    )
    level: int = Field(description="Depth in the outline, starting at 1.")
    title_en: str | None = Field(default=None, description="English heading from the filing.")
    title_ko: str = Field(description="Korean heading.")
    chars: int = Field(description="Rendered characters of the section and its subsections.")
    tables: int = Field(description="Tables in the section and its subsections.")
    placeholder: bool = Field(
        default=False,
        description="True when the section only states that the item is omitted or not applicable, as MD&A sections in semi-annual and quarterly reports do.",
    )
    image_only: bool = Field(
        default=False, description="True when the section's content is images the archive omits."
    )
    parent_id: str | None = Field(default=None, description="Enclosing section ID.")


class SuggestedSection(DocumentModel):
    """A section alias available in this document."""

    alias: str = Field(description="Alias accepted by `section`, such as consolidated_notes.")
    section_ids: list[str] = Field(description="Sections the alias reads, in order.")
    title_en: str | None = Field(default=None, description="English heading of the first section.")


class AmendmentChange(DocumentModel):
    """One corrected item of an amended filing."""

    item: str = Field(description="Corrected item.")
    reason: str | None = Field(default=None, description="Reason for the correction.")
    before: str = Field(description="Text before the correction.")
    after: str = Field(description="Text after the correction.")


class Amendment(DocumentModel):
    """Summary of the correction section that opens an amended filing."""

    original_filed: str | None = Field(
        default=None, description="Filing date of the corrected document (ISO date when parsed)."
    )
    corrected_document: str | None = Field(
        default=None, description="Name of the corrected document."
    )
    reason: str | None = Field(default=None, description="Overall reason, when stated once.")
    section_id: str | None = Field(
        default=None, description="Section holding the full correction text."
    )
    changes: list[AmendmentChange] = Field(
        default_factory=list, description="Corrected items; long texts are shortened."
    )


class Outline(DocumentModel):
    """Map of one document in a filing, without body text."""

    filing_number: str = Field(description="14-digit filing number.")
    document: str = Field(description="Key of the outlined document.")
    documents: list[DocumentInfo] = Field(description="Every document in the archive.")
    sections: list[SectionInfo] = Field(description="Sections in document order.")
    suggested_sections: list[SuggestedSection] = Field(
        default_factory=list, description="Periodic-report aliases present in this document."
    )
    amendment: Amendment | None = Field(
        default=None, description="Correction summary for amended filings."
    )
    notes: list[str] = Field(default_factory=list, description="Coverage gaps and caveats.")


class TableData(DocumentModel):
    """Typed rows of a table that appears in a returned chunk."""

    caption: str | None = Field(default=None, description="Text that introduces the table.")
    unit: str | None = Field(default=None, description="Unit statement in English.")
    header: list[str] = Field(description="Column labels; empty when the table has none.")
    rows: list[list[str]] = Field(description="Rows in this chunk; numbers stay verbatim.")
    layout: TableLayout = Field(description="grid (Markdown table) or form (label: value lines).")
    section_id: str | None = Field(default=None, description="Section containing the table.")
    first_row: int = Field(description="Index of the first returned row within the table.")
    total_rows: int = Field(description="Rows in the whole table.")


class ReadChunk(DocumentModel):
    """A page of rendered Markdown."""

    filing_number: str = Field(description="14-digit filing number.")
    document: str = Field(description="Key of the document read.")
    section: SectionInfo | None = Field(
        default=None, description="Section read; null for the whole document."
    )
    offset: int = Field(description="Character offset of this page within the section or document.")
    next_offset: int | None = Field(
        default=None, description="Offset of the next page; null on the last page."
    )
    total_chars: int = Field(description="Rendered characters of the section or document.")
    truncated: bool = Field(description="True when more content follows this page.")
    content: str = Field(description="Markdown for this page.")
    tables: list[TableData] = Field(default_factory=list, description="Tables in this page.")
    labels: LabelMode = Field(description="Label language used.")
    notes: list[str] = Field(default_factory=list, description="Paging and coverage notes.")


class SearchHit(DocumentModel):
    """A passage that matches a search query."""

    section_id: str | None = Field(default=None, description="Section containing the match.")
    section_title_en: str | None = Field(
        default=None, description="English heading of that section, else its Korean heading."
    )
    offset: int = Field(
        description="Offset of the passage within the searched scope; pass the same `section` to `read`."
    )
    section_offset: int | None = Field(
        default=None, description="Offset of the passage within its own section."
    )
    snippet: str = Field(description="About 300 characters around the match.")


class SearchResult(DocumentModel):
    """Passages matching a query."""

    filing_number: str = Field(description="14-digit filing number.")
    document: str = Field(description="Key of the document searched.")
    section: str | None = Field(default=None, description="Section searched; null for all.")
    query: str = Field(description="Query as given.")
    hits: list[SearchHit] = Field(description="Matching passages in document order.")
    total_hits: int = Field(description="Number of matches in the scope.")
    notes: list[str] = Field(default_factory=list, description="Matching caveats.")


class DocumentStoreStats(DocumentModel):
    """Cache statistics for the server status resource."""

    entries: int = Field(description="Parsed filings in the cache.")
    rendered_chars: int = Field(description="Rendered characters held by cached filings.")
    max_rendered_chars: int = Field(description="Cache budget in rendered characters.")
    hits: int = Field(description="Requests answered from the cache.")
    misses: int = Field(description="Requests that started a download.")
    in_flight: int = Field(description="Downloads or parses still running.")
    failures: int = Field(description="Downloads or parses that failed.")
