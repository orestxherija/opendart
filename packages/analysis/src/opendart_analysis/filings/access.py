"""Paged filing-search access for workflows that page through the filing index themselves.

``opendart_analysis.upstream.SearchFilings`` reads one page of one company's filings for
workflows that need only the newest ones. Filing discovery and the event index need more of
OpenDART's search: market-wide queries, disclosure subtypes, a listing-market filter, page
numbers, and the page counters. ``ReadFilingPage`` reads exactly one upstream page; the
higher-level search policies (merging categories, title scans, page budgets) live in the
workflows, so a source only implements ordinary pagination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from opendart_analysis.upstream import MAX_FILING_PAGE, FilingRecord

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from opendart_analysis.upstream import DisclosureGroup, Volatility

type CorporationType = Literal["Y", "K", "N", "E"]
"""OpenDART corporation type (``corp_cls``): KOSPI, KOSDAQ, KONEX, or other (unlisted)."""


@dataclass(frozen=True, slots=True)
class FilingPageQuery:
    """One page of a filing search, newest first.

    OpenDART filters by subtype only when the group is omitted, so a query names a group or a
    subtype, not both (``opendart_analysis.filings.category_codes`` builds them).

    Attributes:
        corp_code (str | None): 8-digit DART corporation code; None searches every company,
            which OpenDART allows for windows of up to three months.
        start (date): First filing date (KST), inclusive.
        end (date): Last filing date (KST), inclusive.
        group (DisclosureGroup | None): Disclosure type (``pblntf_ty``); None for every type.
        subtype (str | None): Disclosure subtype (``pblntf_detail_ty``), such as ``I002``.
        final_only (bool): Keep only the final version of amended filings.
        corporation_type (CorporationType | None): Listing market to keep; None for all.
        page (int): 1-based page number.
        page_size (int): Filings per page, at most ``MAX_FILING_PAGE``.
    """

    corp_code: str | None
    start: date
    end: date
    group: DisclosureGroup | None = None
    subtype: str | None = None
    final_only: bool = False
    corporation_type: CorporationType | None = None
    page: int = 1
    page_size: int = MAX_FILING_PAGE

    def __post_init__(self) -> None:
        """Reject a window that ends before it starts or a page OpenDART cannot serve.

        Raises:
            ValueError: ``end`` is before ``start``, ``page`` is below 1, or ``page_size`` is
                outside 1 to 100.
        """
        if self.end < self.start:
            message = f"end ({self.end}) is before start ({self.start})."
            raise ValueError(message)
        if self.page < 1:
            message = f"page must be at least 1; got {self.page}."
            raise ValueError(message)
        if not 1 <= self.page_size <= MAX_FILING_PAGE:
            message = f"page_size must be between 1 and {MAX_FILING_PAGE}; got {self.page_size}."
            raise ValueError(message)


class ListedFiling(FilingRecord, Protocol):
    """The fields of one filing-search row that filing discovery reads."""

    @property
    def corporation_code(self) -> str | None:
        """8-digit DART corporation code of the filer."""
        ...

    @property
    def corporation_name(self) -> str | None:
        """Company name as listed."""
        ...

    @property
    def stock_code(self) -> str | None:
        """6-character stock code of a listed company."""
        ...

    @property
    def corporation_type(self) -> str | None:
        """Corporation type: Y (KOSPI), K (KOSDAQ), N (KONEX), or E (other)."""
        ...

    @property
    def submitter_name(self) -> str | None:
        """Name of the submitter."""
        ...

    @property
    def filing_date(self) -> str | None:
        """Filing date as ``YYYYMMDD``."""
        ...

    @property
    def rm(self) -> str | None:
        """Remark letters, such as ``U`` for a filing corrected later."""
        ...


class FilingPage(Protocol):
    """One page of filing-search results with OpenDART's counters."""

    @property
    def list(self) -> Sequence[ListedFiling] | None:
        """Filings on the page, newest first."""
        ...

    @property
    def total_count(self) -> int | None:
        """Filings matching the query across every page, when reported."""
        ...

    @property
    def total_page(self) -> int | None:
        """Pages matching the query, when reported."""
        ...


class ReadFilingPage(Protocol):
    """Read one page of a filing search; bound by the caller to a data source."""

    async def __call__(
        self, query: FilingPageQuery, /, *, volatility: Volatility
    ) -> FilingPage | None:
        """Return one page of filings.

        Args:
            query (FilingPageQuery): Filters, window, and page.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            FilingPage | None: The page, or None when the source has no filings for the query.
        """
        ...
