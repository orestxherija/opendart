"""Markdown views of get_financials results: line items by periods, and holdings.

Quarterly income lines get two columns per period, the three months (Q2 2026) and the year
to date (H1 2026), so the table reads like the filing. Amounts follow ``unit``; per-share
amounts and percentages are never scaled.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.units import unit_label
from opendart_mcp.render.markdown import (
    MISSING_VALUE,
    amount,
    company_line,
    footer,
    join,
    number,
    percent,
    table,
)

if TYPE_CHECKING:
    from opendart_mcp.domain.types import Unit
    from opendart_mcp.models.financials import (
        EquityInvestment,
        FinancialsResult,
        Number,
        RowKind,
        StatementRow,
    )

    type Cell = tuple[str, int, bool]

TITLES: Final = MappingProxyType(
    {
        "summary": "Financial summary",
        "income": "Income statement",
        "balance": "Balance sheet",
        "cash_flow": "Cash flow statement",
        "comprehensive_income": "Statement of comprehensive income",
        "equity_changes": "Statement of changes in equity",
        "ratios": "Financial indicators",
        "equity_investments": "Equity investments",
        "preliminary": "Preliminary earnings",
    }
)
"""Heading per view."""

_QUARTER: Final = MappingProxyType({"Q1": "Q1", "H1": "Q2", "Q3": "Q3", "FY": "Q4"})
_YEAR_TO_DATE: Final = MappingProxyType({"Q1": "Q1 ", "H1": "H1 ", "Q3": "9M ", "FY": "FY"})


def _split(rows: list[StatementRow], index: int) -> bool:
    """Tell whether a period needs separate three-month and year-to-date columns.

    Args:
        rows (list[StatementRow]): Table rows.
        index (int): Period position.

    Returns:
        bool: True when any row's year-to-date amount differs from its period amount.
    """
    return any(
        row.cumulative is not None
        and row.cumulative[index] is not None
        and row.cumulative[index] != row.values[index]
        for row in rows
    )


def _columns(result: FinancialsResult) -> list[Cell]:
    """Plan the value columns: header, period position, and whether it is year to date.

    Args:
        result (FinancialsResult): Result.

    Returns:
        list[Cell]: Columns in display order.
    """
    cells: list[Cell] = []
    for index, period in enumerate(result.periods):
        if _split(result.rows, index):
            cells.append((f"{_QUARTER[period.period]} {period.fiscal_year}", index, False))
            cells.append((f"{_YEAR_TO_DATE[period.period]}{period.fiscal_year}", index, True))
        else:
            cells.append((period.label, index, False))
    return cells


def _cell(value: Number | None, kind: RowKind | None, unit: Unit) -> str:
    """Format one value by its kind.

    Args:
        value (Number | None): Value.
        kind (RowKind | None): Row kind; None for won amounts.
        unit (Unit): Display unit for amounts.

    Returns:
        str: Formatted value.
    """
    if value is None:
        return MISSING_VALUE
    if kind == "percent":
        return percent(float(value))
    if kind == "per_share":
        return number(value, decimals=0 if isinstance(value, int) else 2)
    return amount(round(value), unit)


def _label(row: StatementRow, currency: str) -> str:
    """Name a row, marking per-share amounts with their currency.

    Args:
        row (StatementRow): Row.
        currency (str): Currency code.

    Returns:
        str: Row label.
    """
    return f"{row.account} ({currency})" if row.kind == "per_share" else row.account


def _statement_table(result: FinancialsResult) -> str:
    """Render line items by period.

    Args:
        result (FinancialsResult): Result.

    Returns:
        str: Markdown table, or an empty string without rows.
    """
    cells = _columns(result)
    body = []
    for row in result.rows:
        line = [_label(row, result.currency)]
        for _, index, cumulative in cells:
            source = row.cumulative if cumulative else row.values
            value = source[index] if source is not None else None
            line.append(_cell(value, row.kind, result.unit))
        body.append(line)
    headers = ["Account", *(header for header, _, _ in cells)]
    return table(headers, body, numeric=range(1, len(headers)))


def _holding(item: EquityInvestment, unit: Unit, *, detailed: bool) -> list[str]:
    """Format one holding.

    Args:
        item (EquityInvestment): Holding.
        unit (Unit): Display unit for amounts.
        detailed (bool): Include the detailed fields.

    Returns:
        list[str]: Table cells.
    """
    cells = [
        item.name,
        item.purpose or MISSING_VALUE,
        percent(item.ownership_pct),
        number(item.shares),
        amount(item.book_value, unit),
    ]
    if detailed:
        cells += [
            amount(item.opening_book_value, unit),
            amount(item.acquired_or_disposed, unit),
            amount(item.valuation_change, unit),
            amount(item.investee_total_assets, unit),
            amount(item.investee_net_income, unit),
            item.first_acquired.isoformat() if item.first_acquired else MISSING_VALUE,
        ]
    return cells


def _holdings_table(result: FinancialsResult) -> str:
    """Render holdings with their stakes and book values.

    Args:
        result (FinancialsResult): Equity-investments result.

    Returns:
        str: Markdown table and the total line.
    """
    investments = result.investments or []
    detailed = any(item.investee_total_assets is not None for item in investments)
    headers = ["Investee", "Purpose", "Stake", "Shares", "Book value"]
    if detailed:
        headers += [
            "Opening",
            "Acquired (disposed)",
            "Valuation",
            "Investee assets",
            "Investee profit",
            "First acquired",
        ]
    body = [_holding(item, result.unit, detailed=detailed) for item in investments]
    totals = [row for row in result.rows if row.account.startswith("Total")]
    total = ""
    if totals:
        closing, opening = [*totals[-1].values, None, None][:2]
        total = f"Total book value: {_cell(closing, None, result.unit)} (opening {_cell(opening, None, result.unit)})."
    return join(table(headers, body, numeric=range(2, len(headers))), total)


def _derived(result: FinancialsResult) -> str:
    """Summarize derived metrics in one line.

    Args:
        result (FinancialsResult): Result.

    Returns:
        str: Line, or an empty string when nothing was derived.
    """
    parts = [
        f"{key.replace("_", " ")} {percent(value, signed=key.endswith("_growth"))}"
        for key, value in result.derived.items()
    ]
    return f"Derived (computed, see notes): {", ".join(parts)}." if parts else ""


def _unit(result: FinancialsResult) -> str:
    """State the unit of the amounts, when the table has any.

    Args:
        result (FinancialsResult): Result.

    Returns:
        str: Unit sentence, or an empty string.
    """
    has_amounts = bool(result.investments) or any(row.kind is None for row in result.rows)
    if not has_amounts:
        return ""
    label = unit_label(result.unit).replace("KRW", result.currency)
    return f"Amounts in {label}; per-share amounts and percentages are not scaled."


def render_financials(result: FinancialsResult) -> str:
    """Render a get_financials result.

    Args:
        result (FinancialsResult): Result.

    Returns:
        str: Markdown.
    """
    basis = f" ({result.basis_used})" if result.basis_used else ""
    title = f"**{company_line(result.company)}: {TITLES[result.view]}{basis}**"
    if result.investments:
        body = _holdings_table(result)
    elif result.rows:
        body = _statement_table(result)
    else:
        body = "No rows to show."
    return join(title, body, _derived(result), _unit(result), footer(result))
