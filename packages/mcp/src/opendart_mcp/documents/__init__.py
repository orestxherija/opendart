"""Filing documents: parse OpenDART filing archives into outlines, pages, tables, and search.

``disclosures.document`` returns the Korean original of a filing as a ZIP archive of DART XML
or KRX HTML. :func:`parse_filing` turns it into a :class:`ParsedFiling` that renders Markdown
with the filing's own English headings and labels; :class:`DocumentStore` downloads, parses,
and caches filings with single-flight tasks; :func:`extract_preliminary_earnings` reads KRX
preliminary-earnings disclosures. This package does not depend on the MCP framework.
"""

from __future__ import annotations

from opendart_mcp.documents.aliases import ALIASES
from opendart_mcp.documents.archive import ArchiveLimits, Member, decode, read_members
from opendart_mcp.documents.errors import (
    ArchiveTooLargeError,
    DocumentError,
    DownloadPendingError,
    MalformedArchiveError,
    SectionNotFoundError,
    StoreClosedError,
    UnknownDocumentError,
)
from opendart_mcp.documents.filing import (
    DEFAULT_MAX_CHARS,
    MAX_CHARS_CAP,
    MAX_HITS,
    ParsedFiling,
    parse_filing,
)
from opendart_mcp.documents.forms import dart_url
from opendart_mcp.documents.models import (
    Amendment,
    AmendmentChange,
    DocumentFormat,
    DocumentInfo,
    DocumentStoreStats,
    LabelMode,
    Outline,
    ReadChunk,
    SearchHit,
    SearchResult,
    SectionInfo,
    SuggestedSection,
    TableData,
    TableLayout,
)
from opendart_mcp.documents.preliminary import (
    PreliminaryChange,
    PreliminaryEarnings,
    PreliminaryPeriod,
    PreliminaryRow,
    PreliminaryValue,
    extract_preliminary_earnings,
)
from opendart_mcp.documents.store import DocumentStore

ALIAS_NAMES: tuple[str, ...] = tuple(alias.name for alias in ALIASES)
"""Section aliases accepted by ``section`` in periodic reports."""

__all__ = [
    "ALIAS_NAMES",
    "DEFAULT_MAX_CHARS",
    "MAX_CHARS_CAP",
    "MAX_HITS",
    "Amendment",
    "AmendmentChange",
    "ArchiveLimits",
    "ArchiveTooLargeError",
    "DocumentError",
    "DocumentFormat",
    "DocumentInfo",
    "DocumentStore",
    "DocumentStoreStats",
    "DownloadPendingError",
    "LabelMode",
    "MalformedArchiveError",
    "Member",
    "Outline",
    "ParsedFiling",
    "PreliminaryChange",
    "PreliminaryEarnings",
    "PreliminaryPeriod",
    "PreliminaryRow",
    "PreliminaryValue",
    "ReadChunk",
    "SearchHit",
    "SearchResult",
    "SectionInfo",
    "SectionNotFoundError",
    "StoreClosedError",
    "SuggestedSection",
    "TableData",
    "TableLayout",
    "UnknownDocumentError",
    "dart_url",
    "decode",
    "extract_preliminary_earnings",
    "parse_filing",
    "read_members",
]
