"""Failures raised while unpacking, parsing, navigating, or fetching filing documents.

Messages are safe to show to a model: they name sizes, keys, and section IDs, never document
text or credentials. The tool layer turns them into actionable ``ToolError`` messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opendart_mcp.documents.models import SectionInfo


class DocumentError(Exception):
    """Base class for filing-document failures."""


class ArchiveTooLargeError(DocumentError):
    """The archive exceeds a configured size or member-count limit.

    Attributes:
        observed_bytes (int): Observed size in bytes, or the member count when ``measure`` is
            ``"members"``.
        limit (int): The limit that was exceeded, in the same unit.
        measure (str): Which limit was exceeded: ``"compressed bytes"``, ``"member bytes"``,
            ``"expanded bytes"``, or ``"members"``.
    """

    def __init__(
        self, observed_bytes: int, limit: int, *, measure: str = "compressed bytes"
    ) -> None:
        """Record the observed size and the limit it exceeded.

        Args:
            observed_bytes (int): Observed size (or member count for ``"members"``).
            limit (int): The exceeded limit.
            measure (str): Name of the exceeded limit. Defaults to ``"compressed bytes"``.
        """
        super().__init__(f"Archive exceeds the {measure} limit: {observed_bytes:,} > {limit:,}")
        self.observed_bytes = observed_bytes
        self.limit = limit
        self.measure = measure


class MalformedArchiveError(DocumentError):
    """The download is not a readable ZIP archive of filing documents."""


class UnknownDocumentError(DocumentError):
    """The requested document key is not in the filing archive.

    Attributes:
        available (list[str]): Document keys present in the archive.
        document (str | None): The key that was requested, when known.
    """

    def __init__(self, available: list[str], *, document: str | None = None) -> None:
        """Record the available keys and the requested key.

        Args:
            available (list[str]): Document keys present in the archive.
            document (str | None): The key that was requested. Defaults to None.
        """
        requested = f"Unknown document {document!r}" if document else "Unknown document"
        super().__init__(f"{requested}; available: {", ".join(available)}")
        self.available = available
        self.document = document


class SectionNotFoundError(DocumentError):
    """No section matches the requested ID, alias, or heading text.

    Attributes:
        query (str): The section query that matched nothing.
        closest (list[SectionInfo]): Outline entries most similar to the query.
    """

    def __init__(self, query: str, closest: list[SectionInfo]) -> None:
        """Record the failed query and the closest outline entries.

        Args:
            query (str): The section query that matched nothing.
            closest (list[SectionInfo]): Outline entries most similar to the query.
        """
        names = ", ".join(f"{info.id} ({info.title_en or info.title_ko})" for info in closest)
        super().__init__(f"No section matches {query!r}; closest: {names or "none"}")
        self.query = query
        self.closest = closest


class DownloadPendingError(DocumentError):
    """The download or parse is still running after the caller's wait budget.

    The work continues in the background and its result is cached, so a retry in about a
    minute usually succeeds.

    Attributes:
        filing_number (str): Filing whose document is still being prepared.
        waited_s (float): Seconds the caller waited.
    """

    def __init__(self, filing_number: str, waited_s: float) -> None:
        """Record the pending filing and how long the caller waited.

        Args:
            filing_number (str): Filing whose document is still being prepared.
            waited_s (float): Seconds the caller waited.
        """
        super().__init__(
            f"Filing {filing_number} is still downloading after {waited_s:.0f} s; retry shortly"
        )
        self.filing_number = filing_number
        self.waited_s = waited_s


class StoreClosedError(DocumentError):
    """The document store is not running, or shut down while a request waited."""
