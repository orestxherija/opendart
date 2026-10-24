"""Treasury stock tables of periodic reports, summarized by share class.

``tesstk_acqs_dsps_sttus`` lists treasury stock as a hierarchy of acquisition methods (up to
three levels, such as direct acquisition > on-exchange) with subtotal and "Total" rows.
Totals per class come from the total rows when the filer included them, otherwise from the
method rows added up.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from opendart_analysis.capital.shares import COMMON, is_blank, share_class, sum_known
from opendart_analysis.domain.normalize import clean_text, parse_amount
from opendart_analysis.extracts import is_total

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from opendart_analysis.reports import ReportQuery
    from opendart_analysis.upstream import Volatility


class TreasuryRecord(Protocol):
    """The fields of one treasury-stock row that analysis reads."""

    @property
    def stock_knd(self) -> str | None:
        """Share class as filed."""
        ...

    @property
    def acqs_mth1(self) -> str | None:
        """Acquisition method, broadest level, or a total label."""
        ...

    @property
    def acqs_mth2(self) -> str | None:
        """Acquisition method, second level, or a subtotal label."""
        ...

    @property
    def acqs_mth3(self) -> str | None:
        """Acquisition method, narrowest level, or a subtotal label."""
        ...

    @property
    def bsis_qy(self) -> str | None:
        """Treasury shares at the period start."""
        ...

    @property
    def change_qy_acqs(self) -> str | None:
        """Shares acquired during the period."""
        ...

    @property
    def change_qy_dsps(self) -> str | None:
        """Shares disposed of during the period."""
        ...

    @property
    def change_qy_incnr(self) -> str | None:
        """Shares retired during the period."""
        ...

    @property
    def trmend_qy(self) -> str | None:
        """Treasury shares at the period end."""
        ...

    @property
    def rm(self) -> str | None:
        """Note."""
        ...


class FetchTreasuryStock(Protocol):
    """Fetch one company's treasury-stock table for one period; bound by the caller."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[TreasuryRecord] | None:
        """Return the treasury-stock rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[TreasuryRecord] | None: Rows, or None when the source has none.
        """
        ...


@dataclass(frozen=True, slots=True)
class TreasuryMovement:
    """Treasury shares of one class: opening and closing balance and movements in the period.

    Attributes:
        share_class (str): ``common``, ``preferred``, or the class as filed.
        method (str | None): Acquisition method, broadest level first; None for totals.
        begin (int | None): Shares at the period start.
        acquired (int | None): Shares acquired.
        disposed (int | None): Shares disposed of.
        retired (int | None): Shares retired.
        end (int | None): Shares at the period end.
        note (str | None): Note as filed.
    """

    share_class: str
    method: str | None = None
    begin: int | None = None
    acquired: int | None = None
    disposed: int | None = None
    retired: int | None = None
    end: int | None = None
    note: str | None = None


def _movement(record: TreasuryRecord) -> TreasuryMovement:
    """Parse one treasury-stock row.

    Args:
        record (TreasuryRecord): Upstream row.

    Returns:
        TreasuryMovement: Balances and movements, with the acquisition method.
    """
    levels = (
        clean_text(record.acqs_mth1),
        clean_text(record.acqs_mth2),
        clean_text(record.acqs_mth3),
    )
    unique = dict.fromkeys(level for level in levels if level is not None)
    return TreasuryMovement(
        share_class=share_class(record.stock_knd) or COMMON,
        method=" > ".join(unique) or None,
        begin=parse_amount(record.bsis_qy),
        acquired=parse_amount(record.change_qy_acqs),
        disposed=parse_amount(record.change_qy_dsps),
        retired=parse_amount(record.change_qy_incnr),
        end=parse_amount(record.trmend_qy),
        note=clean_text(record.rm),
    )


def _is_leaf(record: TreasuryRecord) -> bool:
    """Check whether a treasury-stock row is a method row rather than a subtotal or total.

    Args:
        record (TreasuryRecord): Upstream row.

    Returns:
        bool: True when no method level is a total label.
    """
    levels = (record.acqs_mth1, record.acqs_mth2, record.acqs_mth3)
    return not any(is_total(level) for level in levels)


def treasury_totals(records: Sequence[TreasuryRecord]) -> list[TreasuryMovement]:
    """Summarize treasury stock by class from the total rows, or from method rows without them.

    Args:
        records (Sequence[TreasuryRecord]): Upstream rows, in filed order.

    Returns:
        list[TreasuryMovement]: One movement per class with activity, without a method;
            filed total rows keep their note.
    """
    totals = [_movement(record) for record in records if is_total(record.acqs_mth1)]
    if not totals:
        totals = _by_class([_movement(record) for record in records if _is_leaf(record)])
    return [
        replace(row, method=None) for row in totals if not is_blank(row, "share_class", "method")
    ]


def _by_class(rows: Iterable[TreasuryMovement]) -> list[TreasuryMovement]:
    """Add up method rows per class.

    Args:
        rows (Iterable[TreasuryMovement]): Method rows.

    Returns:
        list[TreasuryMovement]: One summed movement per class, in first-seen order.
    """
    groups: dict[str, list[TreasuryMovement]] = {}
    for row in rows:
        groups.setdefault(row.share_class, []).append(row)
    return [
        TreasuryMovement(
            share_class=name,
            begin=sum_known(row.begin for row in members),
            acquired=sum_known(row.acquired for row in members),
            disposed=sum_known(row.disposed for row in members),
            retired=sum_known(row.retired for row in members),
            end=sum_known(row.end for row in members),
        )
        for name, members in groups.items()
    ]


def treasury_methods(records: Sequence[TreasuryRecord]) -> list[TreasuryMovement]:
    """List treasury-stock method rows that have activity.

    Args:
        records (Sequence[TreasuryRecord]): Upstream rows, in filed order.

    Returns:
        list[TreasuryMovement]: Method rows without subtotals, totals, or dashes.
    """
    rows = [_movement(record) for record in records if _is_leaf(record)]
    return [row for row in rows if not is_blank(row, "share_class", "method", "note")]
