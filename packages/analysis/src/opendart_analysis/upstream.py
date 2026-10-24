"""Caller-supplied data access, the convention every analysis workflow follows.

Analysis never receives an SDK client. A workflow takes each upstream operation it needs as a
keyword-only async callable typed by a callback Protocol, such as ``search_filings:
SearchFilings``, and the caller binds it to any source: the OpenDART SDK, a cache, or test data.

- Records: a callable returns records that a workflow reads through Protocols naming only the
  fields it uses. Field names follow the OpenDART SDK's models, so SDK records satisfy the
  Protocols as they are; any object with those attributes works.
- No data: a callable returns ``None`` when the source has no data, as OpenDART's status 013
  reports. ``None`` and an empty sequence mean the same to a workflow.
- Volatility: every call states how quickly the requested data can change. The source decides
  whether and how long to cache; analysis keeps no cache and knows no cache lifetimes.
- Failures: exceptions raised by a callable propagate unchanged; analysis never retries.
- Progress: long workflows take an optional ``progress`` callback (``Progress``) that receives
  short messages; ``no_progress`` discards them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import date

type Volatility = Literal["low", "medium", "high"]
"""How quickly requested data can change, from the workflow's knowledge of the data.

``low``: final data that changes only through occasional corrections, such as company profiles
and periodic-report data whose filing window has passed. ``medium``: records that accumulate
during the day but rarely change once filed, such as event reports for a date window.
``high``: data that can change with any new filing, such as filing searches and periodic-report
data still inside its filing window.
"""

type DisclosureGroup = Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
"""OpenDART disclosure type (``pblntf_ty``); ``A`` is periodic reports."""

MAX_FILING_PAGE = 100
"""Most filings OpenDART returns for one search request."""

type Progress = Callable[[str], Awaitable[None]]
"""Async callback that receives short progress messages, such as "3/12 event reports read"."""


async def no_progress(message: str) -> None:
    """Discard a progress message.

    Args:
        message (str): Ignored.
    """
    del message


@dataclass(frozen=True, slots=True)
class FilingQuery:
    """One request for a company's filings, newest first.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        start (date): First filing date (KST), inclusive.
        end (date): Last filing date (KST), inclusive.
        group (DisclosureGroup | None): Disclosure type to keep; None keeps every type.
        final_only (bool): Keep only the final version of amended filings.
        limit (int): Most filings to return, at most ``MAX_FILING_PAGE``.
    """

    corp_code: str
    start: date
    end: date
    group: DisclosureGroup | None = None
    final_only: bool = False
    limit: int = MAX_FILING_PAGE

    def __post_init__(self) -> None:
        """Reject a window that ends before it starts or a limit OpenDART cannot serve.

        Raises:
            ValueError: ``end`` is before ``start``, or ``limit`` is outside 1 to 100.
        """
        if self.end < self.start:
            message = f"end ({self.end}) is before start ({self.start})."
            raise ValueError(message)
        if not 1 <= self.limit <= MAX_FILING_PAGE:
            message = f"limit must be between 1 and {MAX_FILING_PAGE}; got {self.limit}."
            raise ValueError(message)


class FilingRecord(Protocol):
    """The fields of one filing-search result that analysis reads."""

    @property
    def report_title(self) -> str | None:
        """Report title as filed, including any leading amendment marker."""
        ...

    @property
    def filing_number(self) -> str | None:
        """14-digit filing (receipt) number."""
        ...


class SearchFilings(Protocol):
    """Search a company's filings; bound by the caller to a data source."""

    async def __call__(
        self, query: FilingQuery, /, *, volatility: Volatility
    ) -> Sequence[FilingRecord] | None:
        """Return the filings matching a query.

        Args:
            query (FilingQuery): Company, filing-date window, and filters.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[FilingRecord] | None: Matching filings, newest first, or None when the
                source has none.
        """
        ...


class FetchService(Protocol):
    """Call one catalog service by its SDK method name; bound by the caller to a data source.

    Workflows that read many services with one shape, such as periodic-report extracts and
    event reports, take this instead of one Protocol per service. ``service`` and the parameter
    names come from ``opendart_analysis.catalog``; the response is read through the catalog's
    record container and field names.
    """

    async def __call__(
        self, service: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        """Return one service's response.

        Args:
            service (str): SDK method name, such as ``alot_matter``.
            volatility (Volatility): How quickly the answer can change, for the source's cache.
            **params (str | None): Request parameters by SDK name; None omits one.

        Returns:
            object | None: The response, or None when the source has no data.
        """
        ...
