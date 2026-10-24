"""Data access for financial statements: queries, callback Protocols, and the records read.

Follows ``opendart_analysis.upstream``: each callable takes a frozen query and a keyword-only
``volatility``, and returns records or None when the source has no data. Record Protocols
name only the fields the calculations read, under the OpenDART SDK's field names, so the
SDK's list items satisfy them as they are.

- ``FetchMajorAccounts``: one company's major accounts for a period, both bases in one
  answer (the SDK's ``financial_statements.fnltt_singl_acnt``).
- ``FetchFullStatements``: one company's full statements for a period on one basis
  (``financial_statements.fnltt_singl_acnt_all``).
- ``FetchPeerAccounts``: the major accounts of up to 100 companies for a period
  (``financial_statements.fnltt_multi_acnt``).

Indicator, equity-investment, and preliminary-earnings access live with their workflows in
``indicators``, ``investments``, and ``preliminary``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.domain.types import ReportCode
    from opendart_analysis.reports.query import ReportQuery
    from opendart_analysis.upstream import Volatility

type StatementScope = Literal["CFS", "OFS"]
"""OpenDART's statement basis code (``fs_div``): consolidated (CFS) or separate (OFS)."""

MAX_PEERS = 100
"""Most companies one multi-company request covers."""


@dataclass(frozen=True, slots=True)
class StatementQuery:
    """One company's full financial statements for one period and basis.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        fiscal_year (int): Fiscal-year label (``bsns_year``).
        report_code (ReportCode): Report code (``reprt_code``) of the period.
        scope (StatementScope): Consolidated (CFS) or separate (OFS) statements.
    """

    corp_code: str
    fiscal_year: int
    report_code: ReportCode
    scope: StatementScope


@dataclass(frozen=True, slots=True)
class PeerQuery:
    """Several companies' major accounts for one period.

    Attributes:
        corp_codes (tuple[str, ...]): 8-digit DART corporation codes, 1 to ``MAX_PEERS``.
        fiscal_year (int): Fiscal-year label (``bsns_year``).
        report_code (ReportCode): Report code (``reprt_code``) of the period.
    """

    corp_codes: tuple[str, ...]
    fiscal_year: int
    report_code: ReportCode

    def __post_init__(self) -> None:
        """Reject a company count OpenDART cannot serve in one request.

        Raises:
            ValueError: ``corp_codes`` is empty or longer than ``MAX_PEERS``.
        """
        check_peer_count(len(self.corp_codes))


def check_peer_count(count: int) -> None:
    """Reject a company count that one multi-company request cannot cover.

    Args:
        count (int): Number of companies.

    Raises:
        ValueError: ``count`` is outside 1 to ``MAX_PEERS``.
    """
    if not 1 <= count <= MAX_PEERS:
        message = f"Between 1 and {MAX_PEERS} companies are needed; got {count}."
        raise ValueError(message)


class AmountRecord(Protocol):
    """The fields of one statement row that every statement service returns."""

    @property
    def statement_type(self) -> str | None:
        """Statement type (``sj_div``): BS, IS, CIS, CF, or SCE."""
        ...

    @property
    def account_name(self) -> str | None:
        """Account name as filed."""
        ...

    @property
    def current_period_amount(self) -> str | None:
        """Amount for the period (three months for quarterly income lines)."""
        ...

    @property
    def prior_period_amount(self) -> str | None:
        """Amount a year earlier (the prior fiscal year end for balance sheets)."""
        ...

    @property
    def two_periods_prior_amount(self) -> str | None:
        """Amount two years earlier (annual reports)."""
        ...

    @property
    def current_period_cumulative_amount(self) -> str | None:
        """Year-to-date amount for the period (quarterly reports)."""
        ...

    @property
    def prior_period_cumulative_amount(self) -> str | None:
        """Year-to-date amount a year earlier (quarterly reports)."""
        ...

    @property
    def filing_number(self) -> str | None:
        """14-digit filing number of the report."""
        ...

    @property
    def currency(self) -> str | None:
        """Currency code, normally KRW."""
        ...


class MajorAccountRecord(AmountRecord, Protocol):
    """One row of a company's major accounts."""

    @property
    def statement_scope(self) -> str | None:
        """Basis code (``fs_div``): CFS or OFS."""
        ...


class PeerAccountRecord(MajorAccountRecord, Protocol):
    """One row of the multi-company major accounts.

    OpenDART adds an undocumented ``corp_code`` to each row; workflows read it when the record
    has that attribute and fall back to the stock code otherwise.
    """

    @property
    def stock_code(self) -> str | None:
        """6-character stock code of the company the row belongs to."""
        ...


class StatementRecord(AmountRecord, Protocol):
    """One row of a company's full financial statements."""

    @property
    def account_id(self) -> str | None:
        """XBRL account ID, or OpenDART's marker for a company-specific account."""
        ...

    @property
    def account_detail(self) -> str | None:
        """Equity component path (statement of changes in equity); ``-`` elsewhere."""
        ...

    @property
    def frmtrm_q_amount(self) -> str | None:
        """Three-month amount a year earlier (quarterly income lines)."""
        ...


class FetchMajorAccounts(Protocol):
    """Fetch one company's major accounts; bound by the caller to a data source."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[MajorAccountRecord] | None:
        """Return the major accounts of a company and period, both bases.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[MajorAccountRecord] | None: Rows, or None when the source has none.
        """
        ...


class FetchFullStatements(Protocol):
    """Fetch one company's full statements on one basis; bound by the caller."""

    async def __call__(
        self, query: StatementQuery, /, *, volatility: Volatility
    ) -> Sequence[StatementRecord] | None:
        """Return every statement row of a company, period, and basis.

        Args:
            query (StatementQuery): Company, period, and basis.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[StatementRecord] | None: Rows, or None when the source has none.
        """
        ...


class FetchPeerAccounts(Protocol):
    """Fetch several companies' major accounts in one request; bound by the caller."""

    async def __call__(
        self, query: PeerQuery, /, *, volatility: Volatility
    ) -> Sequence[PeerAccountRecord] | None:
        """Return the major accounts of several companies for one period, both bases.

        Args:
            query (PeerQuery): Companies and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[PeerAccountRecord] | None: Rows, or None when the source has none.
        """
        ...
