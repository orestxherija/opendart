"""Present statement lines as get_financials tables: concise selection, columns, and rows.

``opendart_analysis.financials`` turns OpenDART's rows into lines by period and merges
reports; this module decides which lines a concise result shows and lays them out as the
output model's columns and rows. Amounts stay in won; the text renderer scales them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.periods import period_end
from opendart_mcp.models.financials import PeriodColumn, StatementRow

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.financials import Line

MIN_KEY_LINES: Final = 3
"""Fewest key lines a concise table needs before it falls back to the first lines."""

FALLBACK_LINES: Final = 15
"""Lines a concise table shows when a statement uses few standard account IDs."""

_AVAILABLE_NAMES: Final = 12


def _matches(line: Line, needles: Sequence[str]) -> bool:
    """Tell whether a line's name or ID contains any filter text.

    Args:
        line (Line): Line item.
        needles (Sequence[str]): Case-folded filter texts.

    Returns:
        bool: True when any filter matches.
    """
    haystack = f"{line.account}\n{line.account_id or ""}".casefold()
    return any(needle in haystack for needle in needles)


def _filtered(ordered: list[Line], accounts: Sequence[str]) -> tuple[list[Line], str | None]:
    """Keep lines whose name or ID contains any filter text.

    Args:
        ordered (list[Line]): Lines in reading order.
        accounts (Sequence[str]): Filter texts.

    Returns:
        tuple[list[Line], str | None]: Matching lines, or none with a note naming lines.
    """
    needles = [text.strip().casefold() for text in accounts if text.strip()]
    kept = [line for line in ordered if _matches(line, needles)]
    if kept or not ordered:
        return kept, None
    names = ", ".join(line.account for line in ordered[:_AVAILABLE_NAMES])
    return [], f"No line matches accounts={list(accounts)}; lines include {names}."


def select(
    lines: Iterable[Line], *, accounts: Sequence[str] | None, detailed: bool, key_limit: int
) -> tuple[list[Line], str | None]:
    """Choose and order the lines to show.

    Args:
        lines (Iterable[Line]): Candidate lines.
        accounts (Sequence[str] | None): Substring filters on account names and IDs.
        detailed (bool): Show every line instead of the key lines.
        key_limit (int): Lines ranked below this are key lines.

    Returns:
        tuple[list[Line], str | None]: Lines in reading order and a note about hidden lines.
    """
    ordered = sorted(lines, key=lambda line: line.rank)
    if accounts:
        return _filtered(ordered, accounts)
    if detailed:
        return ordered, None
    key = [line for line in ordered if line.rank < key_limit]
    shown = key if len(key) >= MIN_KEY_LINES else ordered[:FALLBACK_LINES]
    if len(shown) == len(ordered):
        return shown, None
    note = f'Showing {len(shown)} key lines of {len(ordered)}; pass response_format="detailed" for every line, or accounts to filter by name.'
    return shown, note


def column(ref: PeriodRef, *, fye_month: int) -> PeriodColumn:
    """Describe a period as a table column.

    Args:
        ref (PeriodRef): Period.
        fye_month (int): Fiscal year-end month, for periods without an end date.

    Returns:
        PeriodColumn: Output column.
    """
    end = ref.end_date or period_end(ref.fiscal_year, ref.period, fye_month=fye_month)
    return PeriodColumn(
        label=ref.label, end_date=end, fiscal_year=ref.fiscal_year, period=ref.period
    )


def to_rows(
    lines: Sequence[Line], periods: Sequence[PeriodRef], *, detailed: bool
) -> list[StatementRow]:
    """Align lines with the table's columns.

    Args:
        lines (Sequence[Line]): Lines in display order.
        periods (Sequence[PeriodRef]): Periods in display order.
        detailed (bool): Include account IDs.

    Returns:
        list[StatementRow]: Output rows.
    """
    return [
        StatementRow(
            account=line.account,
            account_id=line.account_id if detailed else None,
            kind=line.kind,
            values=[line.values.get(ref) for ref in periods],
            cumulative=[line.cumulative.get(ref) for ref in periods] if line.cumulative else None,
        )
        for line in lines
    ]
