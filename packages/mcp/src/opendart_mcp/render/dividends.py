"""Markdown view of dividend history: one row per measure and share class, one column per year."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.render.markdown import (
    amount,
    company_line,
    footer,
    join,
    number,
    percent,
    table,
)

if TYPE_CHECKING:
    from opendart_analysis.domain.types import Unit
    from opendart_mcp.models.dividends import DividendRow, DividendsResult

UNIT: Final[Unit] = "million_krw"
_NAMES: Final = {
    "cash_dps": "Cash dividend per share (KRW)",
    "stock_dps": "Stock dividend per share (shares)",
    "cash_dividends": "Total cash dividends (KRW million)",
    "stock_dividends": "Total stock dividends (KRW million)",
    "payout_ratio": "Cash payout ratio",
    "cash_yield": "Cash dividend yield, as filed",
    "stock_yield": "Stock dividend yield, as filed",
    "net_income": "Net income (KRW million)",
    "eps": "EPS (KRW)",
    "par_value": "Par value (KRW)",
}


def _name(row: DividendRow) -> str:
    """Describe a row's measure and earnings basis.

    Args:
        row (DividendRow): Dividend row.

    Returns:
        str: Display label.
    """
    name = _NAMES.get(row.measure) or row.label or row.measure
    return f"{name}, {row.basis}" if row.basis else name


def _cell(row: DividendRow, year: int) -> str:
    """Format one value in the row's unit.

    Args:
        row (DividendRow): Dividend row.
        year (int): Fiscal year.

    Returns:
        str: Formatted value, or a dash when missing.
    """
    filed = row.values_by_year.get(str(year))
    if filed is None or row.unit == "%":
        return percent(filed, decimals=2)
    if row.unit == "KRW":
        return amount(int(filed), UNIT)
    return number(filed, decimals=0 if isinstance(filed, int) else 4)


def render_dividends(result: DividendsResult) -> str:
    """Render a dividend history.

    Args:
        result (DividendsResult): Dividend history.

    Returns:
        str: Markdown.
    """
    years = result.fiscal_years
    headers = ("Measure", "Share class", *(f"FY{year}" for year in years))
    rows = [(_name(row), row.share_class, *(_cell(row, y) for y in years)) for row in result.rows]
    return join(
        f"**Dividends: {company_line(result.company)}**",
        table(headers, rows, numeric=range(2, len(headers))),
        footer(result),
    )
