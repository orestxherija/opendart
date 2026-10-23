"""Preliminary earnings from KRX fair disclosures.

The "Report on Business Performance according to Consolidated Financial Statements (Fair
Disclosure)" template (``연결재무제표기준영업(잠정)실적(공정공시)``) defines the periods, then
reports revenue, operating profit, pretax profit, net profit, and net profit attributable to
owners for the quarter and the year to date, with quarter-on-quarter and year-on-year change
and turnaround flags. Units differ by filer and by release: Samsung's early-month guidance
uses trillion won (``195.00``), its month-end release 100 million won, others million won.
Values are converted to won exactly; the verbatim strings are kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from opendart_mcp.documents.tables import expand
from opendart_mcp.documents.tree import Section, Table, collapse, compact
from opendart_mcp.documents.units import find_unit_statement, won_unit

if TYPE_CHECKING:
    from opendart_mcp.documents.filing import ParsedFiling
    from opendart_mcp.documents.tree import Block

Metric = Literal[
    "revenue",
    "operating_profit",
    "pretax_profit",
    "net_profit",
    "net_profit_attributable_to_owners",
]
"""Reported line item."""

PeriodKey = Literal[
    "current_quarter", "prior_quarter", "year_ago_quarter", "year_to_date", "prior_year_to_date"
]
"""Reporting period defined by the disclosure."""

Turnaround = Literal[
    "turned_profit",
    "turned_loss",
    "loss_continued",
    "loss_widened",
    "loss_narrowed",
    "profit_continued",
    "other",
]
"""Normalized turnaround flag (``흑자적자전환여부``)."""

_PERIODS: dict[str, PeriodKey] = {
    "당기실적": "current_quarter",
    "전기실적": "prior_quarter",
    "전년동기실적": "year_ago_quarter",
    "당기누계실적": "year_to_date",
    "당기누적실적": "year_to_date",
    "전년동기누적실적": "prior_year_to_date",
    "전년동기누계실적": "prior_year_to_date",
}
# Order matters: 법인세비용차감전계속영업이익 contains 영업이익, and owners' net profit 순이익.
_METRICS: tuple[tuple[Metric, tuple[str, ...]], ...] = (
    ("net_profit_attributable_to_owners", ("지배기업", "지배주주")),
    ("pretax_profit", ("법인세비용차감전", "세전")),
    ("revenue", ("매출액", "영업수익", "수익(매출액)")),
    ("operating_profit", ("영업이익",)),
    ("net_profit", ("당기순이익", "순이익")),
)
_PROFIT_LINES: frozenset[str] = frozenset(
    {"pretax_profit", "net_profit", "net_profit_attributable_to_owners"}
)
_ROLES: dict[str, str] = {"당기실적": "current", "전기실적": "prior", "전년동기실적": "year_ago"}
_TURNAROUNDS: dict[str, Turnaround] = {
    "흑자전환": "turned_profit",
    "적자전환": "turned_loss",
    "적자지속": "loss_continued",
    "적자확대": "loss_widened",
    "적자축소": "loss_narrowed",
    "흑자지속": "profit_continued",
}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BLANKS = frozenset({"", "-", "\u2013", "\u2014", "N/A", "n/a"})
_NEGATIVE_MARKS = ("-", "△", "▲", "(")
_TEMPLATE = "잠정)실적"
_QUARTER, _CUMULATIVE = "당해실적", "누계실적"


class PreliminaryModel(BaseModel):
    """Base for preliminary-earnings results: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class PreliminaryPeriod(PreliminaryModel):
    """A period the disclosure defines."""

    key: PeriodKey = Field(description="Period role.")
    label_ko: str = Field(description="Korean period label, such as 당기실적.")
    start: str | None = Field(default=None, description="First day (ISO date).")
    end: str | None = Field(default=None, description="Last day (ISO date).")
    column_label: str | None = Field(
        default=None, description="Column label in the results table, such as ('26.2Q)."
    )


class PreliminaryValue(PreliminaryModel):
    """An amount in won with its verbatim text."""

    krw: int | None = Field(default=None, description="Amount in won; null when not reported.")
    raw: str = Field(description="Verbatim cell text.")


class PreliminaryChange(PreliminaryModel):
    """A change between periods with its turnaround flag."""

    percent: float | None = Field(default=None, description="Change in percent; null if none.")
    raw: str = Field(description="Verbatim change cell.")
    turnaround: Turnaround | None = Field(
        default=None, description="Turnaround flag; null when the filing reports none."
    )
    turnaround_raw: str | None = Field(default=None, description="Verbatim turnaround cell.")


class PreliminaryRow(PreliminaryModel):
    """One reported line item."""

    metric: Metric = Field(description="Line item.")
    label_ko: str = Field(description="Korean row label.")
    current_quarter: PreliminaryValue = Field(description="Current quarter.")
    prior_quarter: PreliminaryValue = Field(description="Prior quarter.")
    year_ago_quarter: PreliminaryValue = Field(description="Same quarter a year earlier.")
    quarter_on_quarter: PreliminaryChange = Field(description="Change versus the prior quarter.")
    year_on_year: PreliminaryChange = Field(description="Change versus the year-ago quarter.")
    year_to_date: PreliminaryValue = Field(description="Current year to date.")
    prior_year_to_date: PreliminaryValue = Field(description="Prior year to date.")
    year_to_date_change: PreliminaryChange = Field(description="Year-to-date change versus prior.")


class PreliminaryEarnings(PreliminaryModel):
    """Preliminary (unaudited) results from a KRX fair disclosure."""

    filing_number: str = Field(description="14-digit filing number.")
    company_name: str | None = Field(default=None, description="Korean company name.")
    basis: Literal["consolidated", "separate"] = Field(description="Statement basis.")
    unit_label: str | None = Field(default=None, description="Stated unit, such as KRW trillion.")
    unit_multiplier: int | None = Field(default=None, description="Won per stated unit.")
    unit_raw: str | None = Field(default=None, description="Verbatim unit statement.")
    periods: list[PreliminaryPeriod] = Field(description="Periods the disclosure defines.")
    rows: list[PreliminaryRow] = Field(description="Line items in filing order.")
    is_amendment: bool = Field(description="Whether this disclosure corrects an earlier one.")
    notes: list[str] = Field(default_factory=list, description="Caveats.")


def extract_preliminary_earnings(parsed: ParsedFiling) -> PreliminaryEarnings | None:
    """Extract preliminary earnings from a KRX fair disclosure.

    Args:
        parsed (ParsedFiling): A parsed filing.

    Returns:
        PreliminaryEarnings | None: The results, or None when the filing does not use the
            preliminary-earnings template.
    """
    tree = parsed.tree()
    if tree is None or tree.format != "krx_html":
        return None
    if _TEMPLATE not in compact(tree.form_name_ko or ""):
        return None
    grids = [_grid(table) for table in _tables(tree.items)]
    found = next((columns for grid in grids if (columns := _columns(grid)) is not None), None)
    if found is None:
        return None
    statement = next((s for row in found.grid for c in row if (s := find_unit_statement(c))), None)
    unit = won_unit(statement.body) if statement is not None else None
    rows = _rows(found, unit[0] if unit else None)
    return PreliminaryEarnings(
        filing_number=parsed.filing_number,
        company_name=tree.company_name,
        basis="consolidated" if "연결" in (tree.form_name_ko or "") else "separate",
        unit_label=unit[1] if unit else None,
        unit_multiplier=unit[0] if unit else None,
        unit_raw=statement.raw if statement else None,
        periods=_periods(grids, found),
        rows=rows,
        is_amendment=parsed.amendment is not None,
        notes=_notes(rows, unit),
    )


@dataclass(frozen=True, slots=True)
class _Columns:
    """Column positions of the results table."""

    grid: list[list[str]]
    first_row: int
    labels: list[str]
    positions: dict[str, int]

    def cell(self, row: list[str], role: str) -> str:
        """Return a row's text in a role's column.

        Args:
            row (list[str]): Data row.
            role (str): Column role.

        Returns:
            str: Cell text, or an empty string when the column is absent.
        """
        index = self.positions.get(role)
        return row[index] if row and index is not None and index < len(row) else ""


def _tables(items: tuple[Block | Section, ...]) -> list[Table]:
    """List tables among items and their subsections.

    Args:
        items (tuple[Block | Section, ...]): Items to search.

    Returns:
        list[Table]: Tables in document order.
    """
    found: list[Table] = []
    for item in items:
        if isinstance(item, Table):
            found.append(item)
        elif isinstance(item, Section):
            found.extend(_tables(item.items))
    return found


def _grid(table: Table) -> list[list[str]]:
    """Expand a table with every span repeated, using the Korean text.

    Args:
        table (Table): Table as written.

    Returns:
        list[list[str]]: Rectangular grid of cell texts.
    """
    return [[slot.cell.label.ko if slot else "" for slot in row] for row in expand(table)]


def _columns(grid: list[list[str]]) -> _Columns | None:
    """Locate the results table's header rows and value columns.

    Args:
        grid (list[list[str]]): Candidate table.

    Returns:
        _Columns | None: Column positions, or None when the table is not the results table.
    """
    for index, row in enumerate(grid[:-1]):
        groups = [compact(text) for text in row]
        if "당기실적" in groups and "전기실적" in groups:
            subs = [compact(text) for text in grid[index + 1]]
            positions = _positions(groups, subs)
            if {"current", "prior", "year_ago"} <= positions.keys():
                return _Columns(grid, index + 2, grid[index + 1], positions)
    return None


def _positions(groups: list[str], subs: list[str]) -> dict[str, int]:
    """Assign value columns from the two header rows.

    Args:
        groups (list[str]): Compact first header row (spans repeated).
        subs (list[str]): Compact second header row.

    Returns:
        dict[str, int]: Column index by role.
    """
    positions: dict[str, int] = {}
    for index, (group, sub) in enumerate(zip(groups, subs, strict=False)):
        role = _ROLES.get(group) or _change_role(group, sub)
        if role is not None:
            positions.setdefault(role, index)
    return positions


def _change_role(group: str, sub: str) -> str | None:
    """Classify a change column under 전기대비 or 전년동기대비.

    Args:
        group (str): Compact group header.
        sub (str): Compact sub-header.

    Returns:
        str | None: ``quarter`` or ``year`` with ``_pct`` or ``_turn``, or None.
    """
    prefix = {"전기대비": "quarter", "전년동기대비": "year"}.get(group)
    if prefix is None:
        return None
    if "증감" in sub:
        return f"{prefix}_pct"
    return f"{prefix}_turn" if "전환" in sub else None


def _rows(columns: _Columns, multiplier: int | None) -> list[PreliminaryRow]:
    """Read the reported line items.

    Args:
        columns (_Columns): Results table and its column positions.
        multiplier (int | None): Won per stated unit.

    Returns:
        list[PreliminaryRow]: Line items in filing order.
    """
    found: dict[Metric, dict[str, list[str]]] = {}
    labels: dict[Metric, str] = {}
    for row in columns.grid[columns.first_row :]:
        metric = _metric(compact(row[0]))
        if metric is None or len(row) < 2:  # noqa: PLR2004 - label and period columns
            continue
        period = _CUMULATIVE if any(k in compact(row[1]) for k in ("누계", "누적")) else _QUARTER
        found.setdefault(metric, {}).setdefault(period, row)
        labels.setdefault(metric, collapse(row[0]))
    return [
        _row(metric, labels[metric], parts, columns=columns, multiplier=multiplier)
        for metric, parts in found.items()
    ]


def _metric(label: str) -> Metric | None:
    """Classify a row label.

    Args:
        label (str): Compact row label.

    Returns:
        Metric | None: The line item, or None.
    """
    for metric, keys in _METRICS:
        if any(key in label for key in keys):
            return metric
    return None


def _row(
    metric: Metric,
    label: str,
    parts: dict[str, list[str]],
    *,
    columns: _Columns,
    multiplier: int | None,
) -> PreliminaryRow:
    """Build one line item from its quarter and cumulative rows.

    Args:
        metric (Metric): Line item.
        label (str): Korean row label.
        parts (dict[str, list[str]]): Quarter and cumulative rows.
        columns (_Columns): Column positions.
        multiplier (int | None): Won per stated unit.

    Returns:
        PreliminaryRow: The line item.
    """
    quarter, cumulative = parts.get(_QUARTER, []), parts.get(_CUMULATIVE, [])
    return PreliminaryRow(
        metric=metric,
        label_ko=label,
        current_quarter=_value(columns.cell(quarter, "current"), multiplier),
        prior_quarter=_value(columns.cell(quarter, "prior"), multiplier),
        year_ago_quarter=_value(columns.cell(quarter, "year_ago"), multiplier),
        quarter_on_quarter=_change(columns, quarter, "quarter"),
        year_on_year=_change(columns, quarter, "year"),
        year_to_date=_value(columns.cell(cumulative, "current"), multiplier),
        prior_year_to_date=_value(columns.cell(cumulative, "year_ago"), multiplier),
        year_to_date_change=_change(columns, cumulative, "year"),
    )


def _value(raw: str, multiplier: int | None) -> PreliminaryValue:
    """Convert a stated amount to won.

    Args:
        raw (str): Cell text such as ``1,714,995`` or ``195.00``.
        multiplier (int | None): Won per stated unit.

    Returns:
        PreliminaryValue: Amount in won (exact, rounded to the won) and the verbatim text.
    """
    number = _decimal(raw)
    krw = None
    if number is not None and multiplier is not None:
        krw = int((number * multiplier).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    return PreliminaryValue(krw=krw, raw=collapse(raw))


def _change(columns: _Columns, row: list[str], prefix: str) -> PreliminaryChange:
    """Read a percent change and its turnaround flag.

    Args:
        columns (_Columns): Column positions.
        row (list[str]): Data row.
        prefix (str): ``quarter`` (versus the prior quarter) or ``year`` (versus a year earlier).

    Returns:
        PreliminaryChange: The change.
    """
    percent_raw = columns.cell(row, f"{prefix}_pct")
    turn_raw = collapse(columns.cell(row, f"{prefix}_turn"))
    number = _decimal(percent_raw)
    flag = compact(turn_raw)
    return PreliminaryChange(
        percent=float(number) if number is not None else None,
        raw=collapse(percent_raw),
        turnaround=None if flag in _BLANKS else _TURNAROUNDS.get(flag, "other"),
        turnaround_raw=turn_raw or None,
    )


def _decimal(raw: str) -> Decimal | None:
    """Parse a number with commas and Korean negative marks.

    Args:
        raw (str): Cell text such as ``-1,234``, ``(1,234)``, or ``△1,234``.

    Returns:
        Decimal | None: The number, or None for blanks and non-numbers.
    """
    text = raw.strip().replace(",", "").replace(" ", "")
    if text in _BLANKS:
        return None
    negative = text.startswith(_NEGATIVE_MARKS)
    try:
        number = Decimal(text.strip("-△▲()+"))
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return -number if negative else number


def _periods(grids: list[list[list[str]]], columns: _Columns) -> list[PreliminaryPeriod]:
    """Read the period definitions and attach the results table's column labels.

    Args:
        grids (list[list[list[str]]]): Every table of the page.
        columns (_Columns): Results table column positions.

    Returns:
        list[PreliminaryPeriod]: Periods in filing order, each once.
    """
    roles = {"current_quarter": "current", "prior_quarter": "prior", "year_ago_quarter": "year_ago"}
    periods: dict[PeriodKey, PreliminaryPeriod] = {}
    for row in (row for grid in grids for row in grid if row):
        key = _PERIODS.get(compact(row[0]))
        if key is None or key in periods:
            continue
        dates = list(dict.fromkeys(_DATE.findall(" ".join(row[1:]))))
        role = roles.get(key)
        periods[key] = PreliminaryPeriod(
            key=key,
            label_ko=collapse(row[0]),
            start=dates[0] if dates else None,
            end=dates[1] if len(dates) > 1 else None,
            column_label=collapse(columns.cell(columns.labels, role)) or None if role else None,
        )
    return list(periods.values())


def _notes(rows: list[PreliminaryRow], unit: tuple[int, str] | None) -> list[str]:
    """List caveats for the extracted results.

    Args:
        rows (list[PreliminaryRow]): Extracted line items.
        unit (tuple[int, str] | None): Stated won unit.

    Returns:
        list[str]: Notes.
    """
    notes = ["Preliminary, unaudited figures from a KRX fair disclosure; final results may differ."]
    if unit is None:
        notes.append("No unit statement was found, so amounts are not converted to won.")
    unreported = [
        row for row in rows if row.metric in _PROFIT_LINES and row.current_quarter.krw is None
    ]
    if unreported and len(unreported) == sum(row.metric in _PROFIT_LINES for row in rows):
        notes.append("Only revenue and operating profit are reported in this release.")
    return notes
