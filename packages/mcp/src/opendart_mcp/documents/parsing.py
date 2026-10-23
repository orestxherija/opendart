"""Turn one archive member's bytes into a document tree.

Members are decoded incrementally and fed to the parser in chunks, so the decoded text of a
large member is never held in memory at once. Decoding is strict UTF-8 first; if that fails
anywhere, the member is parsed again as CP949. Declared charsets are ignored.
"""

from __future__ import annotations

import codecs
from typing import TYPE_CHECKING

from opendart_mcp.documents.dart import DartBuilder
from opendart_mcp.documents.krx import KrxBuilder

if TYPE_CHECKING:
    from opendart_mcp.documents.models import DocumentFormat
    from opendart_mcp.documents.tree import DocumentTree

_CHUNK_BYTES = 1 << 20
_SNIFF_BYTES = 4096


def sniff_format(data: bytes) -> DocumentFormat | None:
    """Recognize DART XML or KRX HTML from a member's first bytes.

    Args:
        data (bytes): Member bytes.

    Returns:
        DocumentFormat | None: The format, or None for content that is not markup.
    """
    head = data[:_SNIFF_BYTES].decode("utf-8", errors="ignore").lower()
    if "<document" in head or "dart4.xsd" in head:
        return "dart_xml"
    if "<html" in head or "<body" in head or "<table" in head:
        return "krx_html"
    if head.lstrip("﻿ \t\r\n").startswith("<"):
        return "dart_xml"
    return None


def parse_markup(data: bytes, document_format: DocumentFormat) -> DocumentTree:
    """Parse a member as DART XML or KRX HTML.

    Args:
        data (bytes): Member bytes.
        document_format (DocumentFormat): Format from :func:`sniff_format`.

    Returns:
        DocumentTree: The parsed document.
    """
    try:
        return _feed(data, document_format, encoding="utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return _feed(data, document_format, encoding="cp949", errors="replace")


def _feed(
    data: bytes, document_format: DocumentFormat, *, encoding: str, errors: str
) -> DocumentTree:
    """Decode and parse a member chunk by chunk.

    Args:
        data (bytes): Member bytes.
        document_format (DocumentFormat): Which builder to use.
        encoding (str): Codec name.
        errors (str): Codec error handling.

    Returns:
        DocumentTree: The parsed document.

    Raises:
        UnicodeDecodeError: The bytes are invalid in a strict encoding.
    """
    builder = DartBuilder() if document_format == "dart_xml" else KrxBuilder()
    decoder = codecs.getincrementaldecoder(encoding)(errors=errors)
    for start in range(0, len(data), _CHUNK_BYTES):
        builder.feed(decoder.decode(data[start : start + _CHUNK_BYTES]))
    builder.feed(decoder.decode(b"", final=True))
    return builder.build()
