"""Markdown view of compare_companies results: one row per company, one column per metric."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_mcp.domain.units import unit_label
from opendart_mcp.render.markdown import MISSING_VALUE, amount, footer, join, percent, table

if TYPE_CHECKING:
    from opendart_mcp.domain.types import Unit
    from opendart_mcp.models.common import CompanyRef
    from opendart_mcp.models.compare import ColumnUnit, CompareResult
    from opendart_mcp.models.financials import Number


def _company(company: CompanyRef) -> str:
    """Name a company with its stock code.

    Args:
        company (CompanyRef): Company.

    Returns:
        str: Name and code.
    """
    return f"{company.name} ({company.stock_code})" if company.stock_code else company.name


def _cell(value: Number | None, column_unit: ColumnUnit, unit: Unit) -> str:
    """Format one value by its column's unit.

    Args:
        value (Number | None): Value.
        column_unit (ColumnUnit): krw or pct.
        unit (Unit): Display unit for amounts.

    Returns:
        str: Formatted value.
    """
    if value is None:
        return MISSING_VALUE
    if column_unit == "pct":
        return percent(float(value))
    return amount(round(value), unit)


def _heading(result: CompareResult) -> str:
    """Describe the table's period and basis.

    Args:
        result (CompareResult): Result.

    Returns:
        str: Bold heading.
    """
    if result.fiscal_year is None or result.period is None:
        return f"**Peer comparison ({result.basis} basis)**"
    period = (
        f"FY{result.fiscal_year}"
        if result.period == "FY"
        else f"{result.period} {result.fiscal_year}"
    )
    return f"**Peer comparison: {period}, {result.basis} basis, {result.company_count} companies**"


def render_compare(result: CompareResult) -> str:
    """Render a peer table.

    Args:
        result (CompareResult): Result.

    Returns:
        str: Markdown.
    """
    headers = ["Company", *(column.label for column in result.columns)]
    body = [
        [
            _company(row.company),
            *(
                _cell(value, column.unit, result.unit)
                for value, column in zip(row.values, result.columns, strict=True)
            ),
        ]
        for row in result.rows
    ]
    missing = "; ".join(f"{item.company}: {item.reason}" for item in result.missing)
    amounts = any(column.unit == "krw" for column in result.columns) and body
    return join(
        _heading(result),
        table(headers, body, numeric=range(1, len(headers))),
        f"Not included: {missing}" if missing else "",
        f"Amounts in {unit_label(result.unit)}; percentages as shown." if amounts else "",
        footer(result),
    )
