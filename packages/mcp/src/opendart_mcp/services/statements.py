"""Turn OpenDART statement rows into line items by period, and merge reports over years.

One report supplies several columns. An annual report carries the current, prior, and
two-years-prior fiscal years. A quarterly report carries, for the balance sheet, the period
end and the prior fiscal year end; for income and comprehensive-income lines, the three
months ending at the period end (``thstrm_amount``) with the year to date
(``thstrm_add_amount``) and the same figures a year earlier (``frmtrm_q_amount`` in full
statements, ``frmtrm_amount`` in the summary); and for cash flows and equity changes, year-
to-date amounts for the period and a year earlier. Reports chained over years merge into one
table in which newer reports win, since they carry restatements.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.dates import add_months, month_end
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_decimal
from opendart_analysis.domain.periods import PeriodRef, period_end
from opendart_mcp.models.financials import PeriodColumn, StatementRow
from opendart_mcp.services.accounts import component, is_per_share, normalize, standard_id

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import date

    from opendart.models.financial_statements import (
        FnlttMultiAcntResponseListItem,
        FnlttSinglAcntAllResponseListItem,
        FnlttSinglAcntResponseListItem,
    )
    from opendart_mcp.models.financials import Number, RowKind, StatementBasis

    type Ranker = Callable[[Item, int], int]

MIN_KEY_LINES: Final = 3
"""Fewest key lines a concise table needs before it falls back to the first lines."""

FALLBACK_LINES: Final = 15
"""Lines a concise table shows when a statement uses few standard account IDs."""

_MONTHS_TO_PRIOR_YEAR_END: Final = MappingProxyType({"Q1": 3, "H1": 6, "Q3": 9})
_WITH_CUMULATIVE: Final = frozenset({"IS", "CIS"})
_AVAILABLE_NAMES: Final = 12


@dataclass(frozen=True, slots=True)
class Item:
    """One upstream statement row, reduced to what a table needs.

    Attributes:
        statement (str): Statement type (``sj_div``): BS, IS, CIS, CF, or SCE.
        account (str): Account name as filed.
        account_id (str | None): Standard XBRL account ID, if any.
        detail (str | None): Equity component path (statement of changes in equity only).
        amounts (tuple[str | None, str | None, str | None]): Current, prior, and
            two-years-prior amounts as upstream text.
        cumulative (tuple[str | None, str | None]): Current and prior year-to-date amounts.
        filing_number (str | None): Filing the row comes from.
        currency (str | None): Currency code, normally KRW.
    """

    statement: str
    account: str
    account_id: str | None
    detail: str | None
    amounts: tuple[str | None, str | None, str | None]
    cumulative: tuple[str | None, str | None]
    filing_number: str | None
    currency: str | None


def full_item(row: FnlttSinglAcntAllResponseListItem) -> Item:
    """Reduce a full-statement row.

    Args:
        row (FnlttSinglAcntAllResponseListItem): Row from ``fnltt_singl_acnt_all``.

    Returns:
        Item: Reduced row; quarterly prior-year amounts come from ``frmtrm_q_amount``.
    """
    return Item(
        statement=(row.statement_type or "").strip().upper(),
        account=clean_text(row.account_name) or "",
        account_id=standard_id(row.account_id),
        detail=row.account_detail,
        amounts=(
            row.current_period_amount,
            row.frmtrm_q_amount or row.prior_period_amount,
            row.two_periods_prior_amount,
        ),
        cumulative=(row.current_period_cumulative_amount, row.prior_period_cumulative_amount),
        filing_number=row.filing_number,
        currency=row.currency,
    )


def summary_item(row: FnlttSinglAcntResponseListItem | FnlttMultiAcntResponseListItem) -> Item:
    """Reduce a major-accounts row from the single- or multi-company summary.

    Args:
        row (FnlttSinglAcntResponseListItem | FnlttMultiAcntResponseListItem): Summary row.

    Returns:
        Item: Reduced row without an account ID.
    """
    return Item(
        statement=(row.statement_type or "").strip().upper(),
        account=clean_text(row.account_name) or "",
        account_id=None,
        detail=None,
        amounts=(row.current_period_amount, row.prior_period_amount, row.two_periods_prior_amount),
        cumulative=(row.current_period_cumulative_amount, row.prior_period_cumulative_amount),
        filing_number=row.filing_number,
        currency=row.currency,
    )


@dataclass(slots=True)
class Line:
    """A line item with values keyed by period.

    Attributes:
        key (str): Identity used to merge reports (statement, account, component).
        account (str): Display name.
        account_id (str | None): XBRL account ID or indicator code.
        kind (RowKind | None): Value kind when not a won amount.
        rank (int): Sort position; key accounts have the smallest ranks.
        values (dict[PeriodRef, Number | None]): Amounts per period.
        cumulative (dict[PeriodRef, int | None]): Year-to-date amounts per period.
        name (str): Account name as filed, without the equity component.
    """

    key: str
    account: str
    account_id: str | None
    kind: RowKind | None
    rank: int
    values: dict[PeriodRef, Number | None] = field(default_factory=dict)
    cumulative: dict[PeriodRef, int | None] = field(default_factory=dict)
    name: str = ""


@dataclass(slots=True)
class Report:
    """The lines one report (or a merged chain of reports) supplies.

    Attributes:
        lines (list[Line]): Line items in upstream order.
        filings (list[str]): Filing numbers the lines come from.
        basis (StatementBasis | None): Statements used, where a basis applies.
        currency (str): Currency of the amounts.
    """

    lines: list[Line]
    filings: list[str] = field(default_factory=list)
    basis: StatementBasis | None = None
    currency: str = "KRW"


def filled_periods(lines: Iterable[Line]) -> list[PeriodRef]:
    """List the periods in which any line has a value, latest period end first.

    Args:
        lines (Iterable[Line]): Line items.

    Returns:
        list[PeriodRef]: Distinct periods.
    """
    found: dict[PeriodRef, None] = {}
    for line in lines:
        found.update((ref, None) for ref, value in line.values.items() if value is not None)
        found.update((ref, None) for ref, total in line.cumulative.items() if total is not None)
    return sorted(found, key=_end_key, reverse=True)


def _end_key(ref: PeriodRef) -> tuple[date | int, int]:
    """Sort key placing later period ends first when reversed.

    Args:
        ref (PeriodRef): Period.

    Returns:
        tuple[date | int, int]: End date (or fiscal year) and the fiscal year.
    """
    return (ref.end_date or ref.fiscal_year, ref.fiscal_year)


def _month_end_before(end: date | None, months: int) -> date | None:
    """Return the month end a number of months before a date.

    Args:
        end (date | None): Starting period end.
        months (int): Months to go back.

    Returns:
        date | None: Month end, or None when the start is unknown.
    """
    if end is None:
        return None
    moved = add_months(end, -months)
    return month_end(moved.year, moved.month)


def shift(ref: PeriodRef, years: int) -> PeriodRef:
    """Return the same period a number of fiscal years earlier.

    Args:
        ref (PeriodRef): Period.
        years (int): Fiscal years back.

    Returns:
        PeriodRef: Earlier period with its end date moved by whole years.
    """
    return PeriodRef(
        ref.fiscal_year - years, ref.period, _month_end_before(ref.end_date, 12 * years)
    )


def prior_year_end(ref: PeriodRef) -> PeriodRef:
    """Return the fiscal year end before a quarterly period.

    Args:
        ref (PeriodRef): Q1, H1, or Q3 period.

    Returns:
        PeriodRef: Prior fiscal year, ending months before the period end.
    """
    months = _MONTHS_TO_PRIOR_YEAR_END.get(ref.period, 12)
    return PeriodRef(ref.fiscal_year - 1, "FY", _month_end_before(ref.end_date, months))


def layout(ref: PeriodRef, statement: str) -> tuple[PeriodRef, ...]:
    """List the periods a report's amount columns refer to.

    Args:
        ref (PeriodRef): Period of the report.
        statement (str): Statement type of the row.

    Returns:
        tuple[PeriodRef, ...]: Periods for the current, prior, and two-years-prior amounts.
    """
    if ref.period == "FY":
        return (ref, shift(ref, 1), shift(ref, 2))
    if statement == "BS":
        return (ref, prior_year_end(ref))
    return (ref, shift(ref, 1))


def number(text: str | None) -> Number | None:
    """Parse an amount, keeping integers exact and fractions as floats.

    Args:
        text (str | None): Upstream text.

    Returns:
        Number | None: The value, or None for blanks and junk.
    """
    value = parse_decimal(text)
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _label(item: Item) -> tuple[str, str]:
    """Build a line's display name and merge key.

    Args:
        item (Item): Reduced row.

    Returns:
        tuple[str, str]: Display name (with the equity component) and merge key.
    """
    part = component(item.detail) if item.statement == "SCE" else None
    base = f"{item.statement}:{item.account_id or normalize(item.account)}"
    if part is None:
        return item.account, base
    shown = item.account if part == "Total" else f"{item.account} ({part})"
    return shown, f"{base}:{part}"


def _line(item: Item, ref: PeriodRef, *, rank: int) -> Line:
    """Convert a reduced row into a line keyed by period.

    Args:
        item (Item): Reduced row.
        ref (PeriodRef): Period of the report.
        rank (int): Sort position.

    Returns:
        Line: Line item.
    """
    periods = layout(ref, item.statement)
    account, key = _label(item)
    kind: RowKind | None = "per_share" if is_per_share(item.account_id, item.account) else None
    values = {col: number(text) for col, text in zip(periods, item.amounts, strict=False)}
    cumulative: dict[PeriodRef, int | None] = {}
    if ref.period != "FY" and item.statement in _WITH_CUMULATIVE:
        cumulative = {c: parse_amount(t) for c, t in zip(periods, item.cumulative, strict=False)}
    if all(value is None for value in cumulative.values()):
        cumulative = {}
    return Line(key, account, item.account_id, kind, rank, values, cumulative, item.account)


def build_report(items: Sequence[Item], ref: PeriodRef, *, rank: Ranker) -> Report:
    """Build one report's lines, dropping exact duplicates and numbering repeated names.

    Args:
        items (Sequence[Item]): Reduced rows of one statement selection, in upstream order.
        ref (PeriodRef): Period of the report.
        rank (Ranker): Sort position for a row given its upstream position.

    Returns:
        Report: Lines with filing numbers and currency.
    """
    lines: list[Line] = []
    seen: dict[str, Line] = {}
    repeats: dict[str, int] = {}
    for position, item in enumerate(items):
        line = _line(item, ref, rank=rank(item, position))
        first = seen.setdefault(line.key, line)
        if first is not line:
            if (first.values, first.cumulative) == (line.values, line.cumulative):
                continue
            repeats[first.key] = repeats.get(first.key, 1) + 1
            line.key = f"{first.key}#{repeats[first.key]}"
        lines.append(line)
    filings = list(dict.fromkeys(i.filing_number for i in items if i.filing_number))
    currency = next((i.currency.strip() for i in items if i.currency and i.currency.strip()), "KRW")
    return Report(lines, filings, currency=currency)


def _absorb(target: Line, line: Line) -> None:
    """Fill a line's missing periods from an older report's line.

    Args:
        target (Line): Line from a newer report, updated in place.
        line (Line): Same line from an older report.
    """
    for ref, value in line.values.items():
        if target.values.get(ref) is None:
            target.values[ref] = value
    for ref, total in line.cumulative.items():
        if target.cumulative.get(ref) is None:
            target.cumulative[ref] = total


def merge(reports: Sequence[Report]) -> Report:
    """Merge reports, newest first; older reports only fill periods the newer lack.

    Args:
        reports (Sequence[Report]): At least one report, newest first.

    Returns:
        Report: Combined lines, filings, and the newest report's basis and currency.
    """
    newest = reports[0]
    lines: dict[str, Line] = {}
    for report in reports:
        for line in report.lines:
            target = lines.get(line.key)
            if target is None:
                lines[line.key] = replace(
                    line, values=dict(line.values), cumulative=dict(line.cumulative)
                )
            else:
                _absorb(target, line)
    filings = list(dict.fromkeys(f for report in reports for f in report.filings))
    return Report(list(lines.values()), filings, newest.basis, newest.currency)


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
