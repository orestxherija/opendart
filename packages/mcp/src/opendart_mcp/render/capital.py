"""Markdown view of get_capital_structure, and a table helper that skips empty columns.

Upstream tables carry many columns that are blank for most companies (legacy fields, a
"difference" column, cancellation history), so tables here drop columns with no values.
Share counts and per-share prices are never scaled; amounts raised use KRW million.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.periods import PeriodRef
from opendart_mcp.render.markdown import (
    MISSING_VALUE,
    amount,
    company_line,
    footer,
    join,
    number,
    section,
    table,
    unit_note,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from opendart_analysis.domain.types import ConcretePeriod, Unit
    from opendart_mcp.models.capital import (
        CapitalChange,
        CapitalStructureResult,
        ProceedsUse,
        ShareClassRow,
        TreasuryMovement,
    )

    type Column[R] = tuple[str, Callable[[R], object], bool]

UNIT: Final[Unit] = "million_krw"
NONE_FILED: Final = "None filed in this report."
_CLASS_NAMES: Final = {"common": "Common", "preferred": "Preferred", "total": "Total"}


def sparse_table[R](rows: Sequence[R], columns: Sequence[Column[R]]) -> str:
    """Render rows as a table, dropping columns that are empty in every row.

    Args:
        rows (Sequence[R]): Rows to render.
        columns (Sequence[Column[R]]): Header, cell function, and whether the column is
            numeric (right-aligned).

    Returns:
        str: Markdown table, or an empty string without rows.
    """
    cells = [[cell(row) for _, cell, _ in columns] for row in rows]
    keep = [
        index
        for index in range(len(columns))
        if any(line[index] not in {None, MISSING_VALUE} for line in cells)
    ]
    headers = [columns[index][0] for index in keep]
    numeric = [position for position, index in enumerate(keep) if columns[index][2]]
    return table(headers, [[line[index] for index in keep] for line in cells], numeric=numeric)


def class_name(share_class: str | None) -> str | None:
    """Capitalize the normalized share classes; other classes keep their filed names.

    Args:
        share_class (str | None): Normalized class.

    Returns:
        str | None: Display name.
    """
    return _CLASS_NAMES.get(share_class, share_class) if share_class else None


def period_title(fiscal_year: int | None, period: ConcretePeriod | None, end: date | None) -> str:
    """Describe the periodic report a result comes from.

    Args:
        fiscal_year (int | None): Fiscal year.
        period (ConcretePeriod | None): Period.
        end (date | None): Period end.

    Returns:
        str: Text such as " (FY2025, period end 2025-12-31)", or empty when unknown.
    """
    if fiscal_year is None or period is None:
        return ""
    ending = f", period end {end.isoformat()}" if end else ""
    return f" ({PeriodRef(fiscal_year, period).label}{ending})"


_SHARE_COLUMNS: Final[tuple[Column[ShareClassRow], ...]] = (
    ("Class", lambda r: class_name(r.share_class), False),
    ("Authorized", lambda r: number(r.authorized), True),
    ("Issued", lambda r: number(r.issued), True),
    ("Treasury", lambda r: number(r.treasury), True),
    ("Outstanding", lambda r: number(r.outstanding), True),
    ("Issued to date", lambda r: number(r.issued_to_date), True),
    ("Decreased to date", lambda r: number(r.decreased_to_date), True),
    ("Capital reduction", lambda r: number(r.capital_reduction), True),
    ("Retired from profits", lambda r: number(r.retired_from_profits), True),
    ("Redeemed", lambda r: number(r.redeemed), True),
    ("Other decrease", lambda r: number(r.other_decrease), True),
)
_TREASURY_COLUMNS: Final[tuple[Column[TreasuryMovement], ...]] = (
    ("Class", lambda r: class_name(r.share_class), False),
    ("Method", lambda r: r.method, False),
    ("Start", lambda r: number(r.begin), True),
    ("Acquired", lambda r: number(r.acquired), True),
    ("Disposed", lambda r: number(r.disposed), True),
    ("Retired", lambda r: number(r.retired), True),
    ("End", lambda r: number(r.end), True),
    ("Note", lambda r: r.note, False),
)
_CHANGE_COLUMNS: Final[tuple[Column[CapitalChange], ...]] = (
    ("Date", lambda r: r.date.isoformat() if r.date else None, False),
    ("Type", lambda r: r.kind, False),
    ("Category", lambda r: r.category, False),
    ("Class", lambda r: class_name(r.share_class), False),
    ("Shares", lambda r: number(r.shares), True),
    ("Par value", lambda r: number(r.par_value), True),
    ("Price per share", lambda r: number(r.price), True),
)
_PROCEEDS_COLUMNS: Final[tuple[Column[ProceedsUse], ...]] = (
    ("Offering", lambda r: r.offering, False),
    ("Kind", lambda r: r.kind, False),
    ("Series", lambda r: r.series, False),
    ("Paid", lambda r: r.paid_on.isoformat() if r.paid_on else None, False),
    ("Planned use", lambda r: r.planned_use, False),
    ("Planned", lambda r: amount(r.planned_amount, UNIT), True),
    ("Actual use", lambda r: r.actual_use, False),
    ("Actual", lambda r: amount(r.actual_amount, UNIT), True),
    ("Difference reason", lambda r: r.difference_reason, False),
    ("Amount paid", lambda r: amount(r.amount_paid, UNIT), True),
    ("Plan", lambda r: r.plan, False),
    ("Status", lambda r: r.actual_status, False),
)


def _block[R](title: str, rows: Sequence[R] | None, columns: Sequence[Column[R]]) -> str:
    """Render one requested section; unrequested sections render nothing.

    Args:
        title (str): Section heading.
        rows (Sequence[R] | None): Section rows, or None when not requested.
        columns (Sequence[Column[R]]): Table columns.

    Returns:
        str: Titled table, a "none filed" line, or an empty string.
    """
    if rows is None:
        return ""
    return section(title, sparse_table(rows, columns) or NONE_FILED)


def render_capital_structure(result: CapitalStructureResult) -> str:
    """Render a capital structure result.

    Args:
        result (CapitalStructureResult): Result to render.

    Returns:
        str: Markdown.
    """
    proceeds = result.use_of_proceeds
    period = period_title(result.fiscal_year, result.period, result.period_end)
    return join(
        f"**{company_line(result.company)}: capital structure{period}**",
        _block("Shares", result.shares, _SHARE_COLUMNS),
        f"Share-count note: {result.shares_note}" if result.shares_note else "",
        _block("Treasury stock", result.treasury_stock, _TREASURY_COLUMNS),
        _block("Treasury stock by method", result.treasury_stock_by_method, _TREASURY_COLUMNS),
        _block("Capital changes", result.capital_changes, _CHANGE_COLUMNS),
        _block("Use of proceeds", proceeds, _PROCEEDS_COLUMNS),
        unit_note(UNIT) if proceeds else "",
        footer(result),
    )
