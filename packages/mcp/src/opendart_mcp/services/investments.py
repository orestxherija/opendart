"""Equity investments as a get_financials table (view="equity_investments").

``opendart_analysis.financials`` reads and normalizes the periodic report's investments in
other companies; here the holdings become rows of closing and opening book values plus the
output model's holdings list, the largest first, trimmed in concise results.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Final

from opendart_analysis.financials.investments import opening_period
from opendart_mcp.models.financials import EquityInvestment, StatementRow
from opendart_mcp.services.statements import column

if TYPE_CHECKING:
    from opendart_analysis.financials import Holding, Holdings
    from opendart_mcp.models.financials import PeriodColumn

CONCISE_HOLDINGS: Final = 20
"""Holdings a concise result lists, largest book value first."""

TOTAL_LABEL: Final = "Total (all investments)"
"""Row label of the filing's total line."""

_DETAIL_FIELDS: Final = (
    "first_acquired",
    "opening_book_value",
    "acquired_or_disposed",
    "valuation_change",
    "investee_total_assets",
    "investee_net_income",
)


def _investment(item: Holding, *, detailed: bool) -> EquityInvestment:
    """Show a holding as the output model, without the detail fields in concise results.

    Args:
        item (Holding): Holding.
        detailed (bool): Keep every field.

    Returns:
        EquityInvestment: Output holding.
    """
    fields = asdict(item)
    if not detailed:
        fields.update(dict.fromkeys(_DETAIL_FIELDS))
    return EquityInvestment(**fields)


def _row(item: Holding, label: str | None = None) -> StatementRow:
    """Show a holding as a row of closing and opening book values.

    Args:
        item (Holding): Holding or total line.
        label (str | None): Row label; the holding's name by default.

    Returns:
        StatementRow: Row aligned with (closing, opening) periods.
    """
    return StatementRow(
        account=label or item.name, values=[item.book_value, item.opening_book_value]
    )


def holdings_table(
    holdings: Holdings, *, detailed: bool, fye_month: int
) -> tuple[list[PeriodColumn], list[StatementRow], list[EquityInvestment], str | None]:
    """Lay holdings out as book values by period plus a holdings list.

    Args:
        holdings (Holdings): Normalized holdings.
        detailed (bool): List every holding with every field.
        fye_month (int): Fiscal year-end month, for column end dates.

    Returns:
        tuple[list[PeriodColumn], list[StatementRow], list[EquityInvestment], str | None]:
            Columns (closing, opening), rows, holdings, and a note when holdings are hidden.
    """
    shown = holdings.investments if detailed else holdings.investments[:CONCISE_HOLDINGS]
    rows = [_row(item) for item in shown]
    if holdings.total is not None:
        rows.append(_row(holdings.total, TOTAL_LABEL))
    periods = [column(holdings.ref, fye_month=fye_month)]
    periods.append(column(opening_period(holdings.ref), fye_month=fye_month))
    hidden = len(holdings.investments) - len(shown)
    note = (
        f'Showing the {len(shown)} largest of {len(holdings.investments)} holdings by book value; pass response_format="detailed" for all of them.'
        if hidden
        else None
    )
    investments = [_investment(item, detailed=detailed) for item in shown]
    return periods, rows, investments, note
