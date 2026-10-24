"""Treasury stock tables of periodic reports, summarized by share class.

``tesstk_acqs_dsps_sttus`` lists treasury stock as a hierarchy of acquisition methods (up to
three levels, such as direct acquisition > on-exchange) with subtotal and "Total" rows.
Totals per class come from the total rows when the filer included them, otherwise from the
method rows added up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis.domain.normalize import clean_text, parse_amount
from opendart_mcp.models.capital import TreasuryMovement
from opendart_mcp.services.shares import COMMON, blank, is_total, share_class, sum_known, trim

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from opendart.models.periodic_reports import TesstkAcqsDspsSttusResponseListItem


def _movement(item: TesstkAcqsDspsSttusResponseListItem) -> TreasuryMovement:
    """Parse one treasury-stock row.

    Args:
        item (TesstkAcqsDspsSttusResponseListItem): Upstream row.

    Returns:
        TreasuryMovement: Balances and movements, with the acquisition method.
    """
    levels = (clean_text(item.acqs_mth1), clean_text(item.acqs_mth2), clean_text(item.acqs_mth3))
    unique = dict.fromkeys(level for level in levels if level is not None)
    return TreasuryMovement(
        share_class=share_class(item.stock_knd) or COMMON,
        method=" > ".join(unique) or None,
        begin=parse_amount(item.bsis_qy),
        acquired=parse_amount(item.change_qy_acqs),
        disposed=parse_amount(item.change_qy_dsps),
        retired=parse_amount(item.change_qy_incnr),
        end=parse_amount(item.trmend_qy),
        note=clean_text(item.rm),
    )


def _is_leaf(item: TesstkAcqsDspsSttusResponseListItem) -> bool:
    """Check whether a treasury-stock row is a method row rather than a subtotal or total.

    Args:
        item (TesstkAcqsDspsSttusResponseListItem): Upstream row.

    Returns:
        bool: True when no method level is a total label.
    """
    return not any(is_total(level) for level in (item.acqs_mth1, item.acqs_mth2, item.acqs_mth3))


def treasury_totals(
    items: Sequence[TesstkAcqsDspsSttusResponseListItem] | None, *, detailed: bool
) -> list[TreasuryMovement] | None:
    """Summarize treasury stock by class from the total rows, or from method rows without them.

    Args:
        items (Sequence[TesstkAcqsDspsSttusResponseListItem] | None): Upstream rows, or None
            when the section was not requested.
        detailed (bool): Whether to keep notes.

    Returns:
        list[TreasuryMovement] | None: One movement per class with activity.
    """
    if items is None:
        return None
    totals = [_movement(item) for item in items if is_total(item.acqs_mth1)]
    if not totals:
        totals = _by_class([_movement(item) for item in items if _is_leaf(item)])
    kept = [trim(row, ("method",)) for row in totals if not blank(row, "share_class", "method")]
    return kept if detailed else [trim(row, ("note",)) for row in kept]


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


def treasury_methods(
    items: Sequence[TesstkAcqsDspsSttusResponseListItem] | None,
) -> list[TreasuryMovement] | None:
    """List treasury-stock method rows that have activity.

    Args:
        items (Sequence[TesstkAcqsDspsSttusResponseListItem] | None): Upstream rows, or None
            when the section was not requested.

    Returns:
        list[TreasuryMovement] | None: Method rows without subtotals, totals, or dashes.
    """
    if items is None:
        return None
    rows = [_movement(item) for item in items if _is_leaf(item)]
    return [row for row in rows if not blank(row, "share_class", "method", "note")]
