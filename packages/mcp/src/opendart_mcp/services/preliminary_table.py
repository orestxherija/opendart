"""Preliminary earnings as a line-items-by-periods table (get_financials view="preliminary").

``services.preliminary.latest_preliminary`` finds and parses the company's latest KRX
preliminary-earnings fair disclosure, and ``opendart_analysis.financials.quarter_lines``
lays it out by quarter with derived growth and margins. Here the current quarter, prior
quarter, and year-ago quarter become the columns, with three-month amounts as values and the
year to date as the cumulative amounts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis.financials.quarters import quarter_lines
from opendart_mcp.models.financials import PeriodColumn
from opendart_mcp.services.statements import select, to_rows
from opendart_mcp.services.tables import Table

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_mcp.models.preliminary import PreliminaryResult

_UNAUDITED: Final = "Preliminary (unaudited) results from a KRX fair disclosure, usually filed weeks before the periodic report, which may differ."


def _notes(found: PreliminaryResult) -> list[str]:
    """Collect caveats for a preliminary-earnings table.

    Args:
        found (PreliminaryResult): Parsed disclosure and its filing.

    Returns:
        list[str]: Notes.
    """
    earnings = found.earnings
    notes = [_UNAUDITED, *earnings.notes, *found.notes]
    if earnings.is_amendment:
        notes.append("This disclosure corrects an earlier one.")
    if earnings.unit_label:
        notes.append(
            f"The filing states amounts in {earnings.unit_label}; values are converted to won."
        )
    return notes


def preliminary_table(
    found: PreliminaryResult, *, fye_month: int, accounts: Sequence[str] | None
) -> Table:
    """Lay a preliminary-earnings disclosure out as a table.

    Args:
        found (PreliminaryResult): Parsed disclosure and its filing.
        fye_month (int): Fiscal year-end month, for quarter labels.
        accounts (Sequence[str] | None): Substring filters on line names.

    Returns:
        Table: Quarter columns, line items, derived metrics, and notes.
    """
    table = Table(notes=_notes(found), filings=[found.source], basis=found.earnings.basis)
    laid = quarter_lines(found.earnings, fye_month=fye_month)
    if laid is None:
        table.notes.append("The disclosure does not state its periods, so no table could be built.")
        return table
    refs = [item.ref for item in laid.quarters]
    table.derived = dict(laid.derived)
    shown, note = select(laid.lines, accounts=accounts, detailed=True, key_limit=len(laid.lines))
    table.periods = [
        PeriodColumn(
            label=item.label,
            end_date=item.ref.end_date,
            fiscal_year=item.ref.fiscal_year,
            period=item.ref.period,
        )
        for item in laid.quarters
    ]
    table.rows = to_rows(shown, refs, detailed=False)
    table.notes.extend(text for text in (note, laid.formula) if text)
    return table
