"""Data access for holding reports: the query, callback Protocols, and the records read.

Follows ``opendart_analysis.upstream``: each callable takes a frozen query and a keyword-only
``volatility``, and returns records or None when the source has no data. Record Protocols name
only the fields the workflow reads, under the OpenDART SDK's field names, so the SDK's list
items satisfy them as they are.

- ``FetchMajorHoldings``: one company's 5% holder reports (the SDK's
  ``equity_disclosures.majorstock``).
- ``FetchInsiderHoldings``: one company's executive and major-shareholder ownership reports
  (``equity_disclosures.elestock``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.upstream import Volatility


@dataclass(frozen=True, slots=True)
class HoldingQuery:
    """One company's holding reports, as far back as the source lists them.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
    """

    corp_code: str


class _FiledRecord(Protocol):
    """The fields every holding-report row has."""

    @property
    def filing_number(self) -> str | None:
        """14-digit filing number of the report."""
        ...

    @property
    def filing_date(self) -> str | None:
        """Filing date, such as 2026-10-16."""
        ...

    @property
    def repror(self) -> str | None:
        """Reporter."""
        ...


class MajorHoldingRecord(_FiledRecord, Protocol):
    """The fields of one 5% holder report that analysis reads."""

    @property
    def report_tp(self) -> str | None:
        """Report type, such as General."""
        ...

    @property
    def stkqy(self) -> str | None:
        """Shares held."""
        ...

    @property
    def stkqy_irds(self) -> str | None:
        """Signed change in shares held."""
        ...

    @property
    def stkrt(self) -> str | None:
        """Ownership, in percent."""
        ...

    @property
    def stkrt_irds(self) -> str | None:
        """Signed change in ownership, in percentage points."""
        ...

    @property
    def ctr_stkqy(self) -> str | None:
        """Shares under major contracts."""
        ...

    @property
    def ctr_stkrt(self) -> str | None:
        """Ownership under major contracts, in percent."""
        ...

    @property
    def report_resn(self) -> str | None:
        """Reasons, as a bulleted list."""
        ...


class InsiderHoldingRecord(_FiledRecord, Protocol):
    """The fields of one executive or major-shareholder ownership report that analysis reads."""

    @property
    def isu_exctv_rgist_at(self) -> str | None:
        """Registered or unregistered officer."""
        ...

    @property
    def isu_exctv_ofcps(self) -> str | None:
        """Position."""
        ...

    @property
    def isu_main_shrholdr(self) -> str | None:
        """Major-shareholder status."""
        ...

    @property
    def sp_stock_lmp_cnt(self) -> str | None:
        """Shares held."""
        ...

    @property
    def sp_stock_lmp_irds_cnt(self) -> str | None:
        """Signed change in shares held."""
        ...

    @property
    def sp_stock_lmp_rate(self) -> str | None:
        """Ownership, in percent."""
        ...

    @property
    def sp_stock_lmp_irds_rate(self) -> str | None:
        """Signed change in ownership, in percentage points."""
        ...


class FetchMajorHoldings(Protocol):
    """Fetch one company's 5% holder reports; bound by the caller."""

    async def __call__(
        self, query: HoldingQuery, /, *, volatility: Volatility
    ) -> Sequence[MajorHoldingRecord] | None:
        """Return the company's 5% holder reports.

        Args:
            query (HoldingQuery): Company.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[MajorHoldingRecord] | None: Reports, or None when the source has none.
        """
        ...


class FetchInsiderHoldings(Protocol):
    """Fetch one company's executive and major-shareholder ownership reports."""

    async def __call__(
        self, query: HoldingQuery, /, *, volatility: Volatility
    ) -> Sequence[InsiderHoldingRecord] | None:
        """Return the company's insider ownership reports.

        Args:
            query (HoldingQuery): Company.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[InsiderHoldingRecord] | None: Reports, or None when the source has none.
        """
        ...
