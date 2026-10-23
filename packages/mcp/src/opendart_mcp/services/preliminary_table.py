"""Preliminary earnings as a line-items-by-periods table (get_financials view="preliminary").

``services.preliminary.latest_preliminary`` finds and parses the company's latest KRX
preliminary-earnings fair disclosure. Here its current quarter, prior quarter, and year-ago
quarter become the columns, with three-month amounts as values and the year to date as the
cumulative amounts, and growth and margins are derived from the quarter's figures.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.dates import add_months, month_end
from opendart_mcp.domain.normalize import parse_date
from opendart_mcp.domain.periods import PeriodRef
from opendart_mcp.models.financials import PeriodColumn
from opendart_mcp.services import derived
from opendart_mcp.services.statements import Line, select, to_rows
from opendart_mcp.services.tables import Table

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from opendart_mcp.documents.preliminary import PreliminaryEarnings, PreliminaryRow
    from opendart_mcp.domain.types import ConcretePeriod
    from opendart_mcp.models.preliminary import PreliminaryResult

_LABELS: Final = MappingProxyType(
    {
        "revenue": "Revenue",
        "operating_profit": "Operating profit",
        "pretax_profit": "Profit before tax",
        "net_profit": "Net profit",
        "net_profit_attributable_to_owners": "Net profit attributable to owners",
    }
)
# Preliminary line items under the names derived metrics look up.
_METRICS: Final = MappingProxyType(
    {"revenue": "revenue", "operating_profit": "operating_income", "net_profit": "net_income"}
)
_PERIOD_OF_QUARTER: Final[Mapping[int, ConcretePeriod]] = MappingProxyType(
    {1: "Q1", 2: "H1", 3: "Q3", 4: "FY"}
)
_QUARTER_MONTHS: Final = 3
_YEAR_MONTHS: Final = 12
_UNAUDITED: Final = "Preliminary (unaudited) results from a KRX fair disclosure, usually filed weeks before the periodic report, which may differ."


@dataclass(frozen=True, slots=True)
class Quarter:
    """A fiscal quarter that labels a preliminary-earnings column.

    Attributes:
        ref (PeriodRef): Fiscal year and the report period ending with the quarter.
        label (str): Quarter label, such as Q3 2026.
    """

    ref: PeriodRef
    label: str


def quarter(end: date, *, fye_month: int) -> Quarter:
    """Label the fiscal quarter that ends on a date.

    Args:
        end (date): Quarter end.
        fye_month (int): Fiscal year-end month.

    Returns:
        Quarter: Quarter label and the matching report period (Q2 maps to H1, Q4 to FY).
    """
    number = ((end.month - fye_month - 1) % _YEAR_MONTHS) // _QUARTER_MONTHS + 1
    fiscal_year = end.year if end.month <= fye_month else end.year + 1
    ref = PeriodRef(fiscal_year, _PERIOD_OF_QUARTER[number], end_date=end)
    return Quarter(ref, f"Q{number} {fiscal_year}")


def _months_before(end: date, months: int) -> date:
    """Return the month end a number of months before a date.

    Args:
        end (date): Starting month end.
        months (int): Months back.

    Returns:
        date: Earlier month end.
    """
    moved = add_months(end, -months)
    return month_end(moved.year, moved.month)


def quarters(earnings: PreliminaryEarnings, *, fye_month: int) -> tuple[Quarter, ...] | None:
    """Find the current, prior, and year-ago quarters the disclosure reports.

    Args:
        earnings (PreliminaryEarnings): Parsed disclosure.
        fye_month (int): Fiscal year-end month.

    Returns:
        tuple[Quarter, ...] | None: Three quarters, or None when the current quarter's end is
            not stated.
    """
    ends = {period.key: parse_date(period.end) for period in earnings.periods}
    current = ends.get("current_quarter")
    if current is None:
        return None
    prior = ends.get("prior_quarter") or _months_before(current, _QUARTER_MONTHS)
    year_ago = ends.get("year_ago_quarter") or _months_before(current, _YEAR_MONTHS)
    return tuple(quarter(end, fye_month=fye_month) for end in (current, prior, year_ago))


def _line(row: PreliminaryRow, refs: Sequence[PeriodRef], position: int) -> Line:
    """Turn one reported line item into a line keyed by quarter.

    Args:
        row (PreliminaryRow): Parsed line item.
        refs (Sequence[PeriodRef]): Current, prior, and year-ago quarters.
        position (int): Order in the filing.

    Returns:
        Line: Line with three-month values and year-to-date amounts.
    """
    current, prior, year_ago = refs
    values = (row.current_quarter.krw, row.prior_quarter.krw, row.year_ago_quarter.krw)
    cumulative = {current: row.year_to_date.krw, year_ago: row.prior_year_to_date.krw}
    has_cumulative = any(value is not None for value in cumulative.values())
    return Line(
        key=row.metric,
        account=_LABELS.get(row.metric, row.label_ko),
        account_id=None,
        kind=None,
        rank=position,
        values=dict(zip((current, prior, year_ago), values, strict=True)),
        cumulative={**cumulative, prior: None} if has_cumulative else {},
        name=_METRICS.get(row.metric, row.metric),
    )


def _derived(
    lines: Sequence[Line], refs: Sequence[PeriodRef]
) -> tuple[dict[str, float], str | None]:
    """Derive year-on-year and quarter-on-quarter growth and margins from quarter amounts.

    Args:
        lines (Sequence[Line]): Preliminary lines.
        refs (Sequence[PeriodRef]): Current, prior, and year-ago quarters.

    Returns:
        tuple[dict[str, float], str | None]: Metrics in percent and a note naming the formulas.
    """
    current, prior, year_ago = refs
    amounts = {line.name: line.values for line in lines}
    year_on_year = {k: (v.get(current), v.get(year_ago)) for k, v in amounts.items()}
    quarter_on_quarter = {k: (v.get(current), v.get(prior)) for k, v in amounts.items()}
    result = derived.compute(year_on_year)
    sequential = derived.compute(quarter_on_quarter)
    for key, _ in derived.GROWTH:
        if key in sequential:
            result[key.replace("_growth", "_qoq_growth")] = sequential[key]
    if not result:
        return result, None
    return (
        result,
        "derived: computed in code from the three-month amounts, in percent; *_growth versus the year-ago quarter, *_qoq_growth versus the prior quarter, operating_margin and net_margin = profit / revenue.",
    )


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
    labeled = quarters(found.earnings, fye_month=fye_month)
    if labeled is None:
        table.notes.append("The disclosure does not state its periods, so no table could be built.")
        return table
    refs = [item.ref for item in labeled]
    lines = [_line(row, refs, position) for position, row in enumerate(found.earnings.rows)]
    table.derived, formula = _derived(lines, refs)
    shown, note = select(lines, accounts=accounts, detailed=True, key_limit=len(lines))
    table.periods = [
        PeriodColumn(
            label=item.label,
            end_date=item.ref.end_date,
            fiscal_year=item.ref.fiscal_year,
            period=item.ref.period,
        )
        for item in labeled
    ]
    table.rows = to_rows(shown, refs, detailed=False)
    table.notes.extend(text for text in (note, formula) if text)
    return table
