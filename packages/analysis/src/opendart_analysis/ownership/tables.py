"""Changes of the largest shareholder and minority shareholders, from periodic reports.

``hyslr_chg_sttus`` lists changes of the largest shareholder with dates, the new largest
shareholder, its stake, and the cause; ``mrhl_sttus`` gives the number of minority (small)
shareholders and their combined holding, and is usually filed in annual reports only. Tables
with nothing to report arrive as rows of dashes, which are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from opendart_analysis.capital.shares import is_blank
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date, parse_percent

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Iterable, Sequence

    from opendart_analysis.reports import ReportQuery
    from opendart_analysis.upstream import Volatility


class ControlChangeRecord(Protocol):
    """The fields of one change-of-largest-shareholder row that analysis reads."""

    @property
    def change_on(self) -> str | None:
        """Date of the change."""
        ...

    @property
    def mxmm_shrholdr_nm(self) -> str | None:
        """New largest shareholder."""
        ...

    @property
    def posesn_stock_co(self) -> str | None:
        """Shares held after the change."""
        ...

    @property
    def qota_rt(self) -> str | None:
        """Ownership after the change, in percent."""
        ...

    @property
    def change_cause(self) -> str | None:
        """Cause as filed."""
        ...

    @property
    def rm(self) -> str | None:
        """Note."""
        ...


class MinorityRecord(Protocol):
    """The fields of one minority-shareholder row that analysis reads."""

    @property
    def shrholdr_co(self) -> str | None:
        """Minority shareholders."""
        ...

    @property
    def shrholdr_tot_co(self) -> str | None:
        """All shareholders."""
        ...

    @property
    def shrholdr_rate(self) -> str | None:
        """Minority shareholders' share of all shareholders, in percent."""
        ...

    @property
    def hold_stock_co(self) -> str | None:
        """Shares minority shareholders hold."""
        ...

    @property
    def stock_tot_co(self) -> str | None:
        """Issued shares."""
        ...

    @property
    def hold_stock_rate(self) -> str | None:
        """Minority shareholders' share of issued shares, in percent."""
        ...

    @property
    def stlm_dt(self) -> str | None:
        """Settlement date."""
        ...

    @property
    def filing_number(self) -> str | None:
        """14-digit filing number of the periodic report."""
        ...


class FetchControlChanges(Protocol):
    """Fetch one company's changes of the largest shareholder for one period."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[ControlChangeRecord] | None:
        """Return the change-of-largest-shareholder rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[ControlChangeRecord] | None: Rows, or None when the source has none.
        """
        ...


class FetchMinorityHolders(Protocol):
    """Fetch one company's minority-shareholder table for one period."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[MinorityRecord] | None:
        """Return the minority-shareholder rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[MinorityRecord] | None: Rows, or None when the source has none.
        """
        ...


@dataclass(frozen=True, slots=True)
class ControlChange:
    """A change of the largest shareholder.

    Attributes:
        date (dt.date | None): Date of the change.
        new_largest_shareholder (str | None): Largest shareholder after the change.
        shares (int | None): Shares it held after the change.
        pct (float | None): Its ownership after the change, in percent.
        cause (str | None): Cause as filed.
        note (str | None): Note as filed.
    """

    date: dt.date | None
    new_largest_shareholder: str | None
    shares: int | None
    pct: float | None
    cause: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class MinorityHolders:
    """Minority (small) shareholders and their combined holding.

    Attributes:
        holders (int | None): Minority shareholders.
        total_holders (int | None): All shareholders.
        holder_pct (float | None): Minority shareholders' share of all shareholders.
        shares (int | None): Shares they hold.
        share_pct (float | None): Their share of issued shares.
        total_shares (int | None): Issued shares.
        as_of (dt.date | None): Date of the figures.
    """

    holders: int | None
    total_holders: int | None
    holder_pct: float | None
    shares: int | None
    share_pct: float | None
    total_shares: int | None
    as_of: dt.date | None


def control_changes(records: Iterable[ControlChangeRecord]) -> list[ControlChange]:
    """Parse changes of the largest shareholder, newest first, without rows of dashes.

    Undated changes come last, in filed order.

    Args:
        records (Iterable[ControlChangeRecord]): Upstream rows.

    Returns:
        list[ControlChange]: Changes with at least one value.
    """
    changes = [
        ControlChange(
            date=parse_date(record.change_on),
            new_largest_shareholder=clean_text(record.mxmm_shrholdr_nm),
            shares=parse_amount(record.posesn_stock_co),
            pct=parse_percent(record.qota_rt),
            cause=clean_text(record.change_cause),
            note=clean_text(record.rm),
        )
        for record in records
    ]
    kept = [change for change in changes if not is_blank(change)]
    return sorted(kept, key=lambda c: c.date.toordinal() if c.date else 0, reverse=True)


def minority_holders(
    records: Iterable[MinorityRecord],
) -> tuple[MinorityHolders, str | None] | None:
    """Read the first minority-shareholder row with figures.

    Args:
        records (Iterable[MinorityRecord]): Upstream rows.

    Returns:
        tuple[MinorityHolders, str | None] | None: Figures and the row's filing number, or
            None when no row has figures other than a date.
    """
    for record in records:
        row = MinorityHolders(
            holders=parse_amount(record.shrholdr_co),
            total_holders=parse_amount(record.shrholdr_tot_co),
            holder_pct=parse_percent(record.shrholdr_rate),
            shares=parse_amount(record.hold_stock_co),
            share_pct=parse_percent(record.hold_stock_rate),
            total_shares=parse_amount(record.stock_tot_co),
            as_of=parse_date(record.stlm_dt),
        )
        if not is_blank(row, "as_of"):
            return row, record.filing_number
    return None
