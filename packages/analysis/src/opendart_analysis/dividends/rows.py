"""Classify dividend-table rows and merge them across annual reports.

``alot_matter`` returns one row per measure and share class with values for three fiscal
years: current (``thstrm``), prior (``frmtrm``), and two years prior (``lwfr``). The English
service labels rows in English with the unit in parentheses, such as "Cash dividend per
share (KRW)" or "Total cash dividends (KRW million)", while share classes stay Korean
(보통주 common, 우선주 preferred) and ``-`` marks a missing value. Rows are classified by
keywords in either language, and values are converted from the filed unit to the row's unit,
so totals filed in KRW million become won.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.domain.normalize import clean_text, parse_decimal
from opendart_analysis.extracts.fields import fold, text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from opendart_analysis.domain.periods import PeriodRef

    type Batch = tuple[PeriodRef, Sequence[object]]

type DividendMeasure = Literal[
    "cash_dps",
    "stock_dps",
    "cash_dividends",
    "stock_dividends",
    "payout_ratio",
    "cash_yield",
    "stock_yield",
    "net_income",
    "eps",
    "par_value",
    "other",
]
"""What a dividend row measures; ``other`` keeps rows no rule recognizes."""

type ValueUnit = Literal["KRW", "KRW/share", "%", "shares/share"]
"""Unit of a row's values: won, won per share, percent, or shares per share."""

type EarningsBasis = Literal["consolidated", "separate"]
"""Statements a row's earnings figure comes from."""

MEASURES: Final[tuple[DividendMeasure, ...]] = (
    "cash_dps",
    "stock_dps",
    "cash_dividends",
    "stock_dividends",
    "payout_ratio",
    "cash_yield",
    "stock_yield",
    "net_income",
    "eps",
    "par_value",
    "other",
)
"""Every measure, in the order merged rows are listed: dividends first."""

_COLUMNS: Final = (("thstrm", 0), ("frmtrm", 1), ("lwfr", 2))
# First rule whose keyword groups all match wins; each group needs one of its keywords.
_RULES: Final[tuple[tuple[DividendMeasure, tuple[tuple[str, ...], ...]], ...]] = (
    ("par_value", (("par value", "액면"),)),
    ("payout_ratio", (("payout", "배당성향"),)),
    ("cash_yield", (("rate of return", "yield", "수익률"), ("cash", "현금"))),
    ("stock_yield", (("rate of return", "yield", "수익률"),)),
    ("cash_dividends", (("total", "총액"), ("cash", "현금"))),
    ("stock_dividends", (("total", "총액"),)),
    ("cash_dps", (("per share", "주당"), ("dividend", "배당"), ("cash", "현금"))),
    ("stock_dps", (("per share", "주당"), ("dividend", "배당"))),
    ("eps", (("per share", "주당", "eps"),)),
    ("net_income", (("profit", "income", "earnings", "순이익"),)),
)
# Standard units of the dividend table, used when a label states none.
_UNITS: Final[dict[DividendMeasure, tuple[ValueUnit, int]]] = {
    "cash_dps": ("KRW/share", 1),
    "stock_dps": ("shares/share", 1),
    "cash_dividends": ("KRW", 1_000_000),
    "stock_dividends": ("KRW", 1_000_000),
    "payout_ratio": ("%", 1),
    "cash_yield": ("%", 1),
    "stock_yield": ("%", 1),
    "net_income": ("KRW", 1_000_000),
    "eps": ("KRW/share", 1),
    "par_value": ("KRW/share", 1),
    "other": ("KRW", 1),
}
# Units stated in a label's closing parentheses; None keeps the measure's money unit.
_STATED: Final[tuple[tuple[tuple[str, ...], ValueUnit | None, int], ...]] = (
    (("%",), "%", 1),
    (("million", "백만"), "KRW", 1_000_000),
    (("thousand", "천원"), "KRW", 1_000),
    (("share", "주"), "shares/share", 1),
    (("krw", "원"), None, 1),
)
_UNIT_TEXT: Final = re.compile(r"\(([^()]*)\)\s*$")
_SEPARATE: Final = ("non-consolidated", "nonconsolidated", "separate", "별도")
_CONSOLIDATED: Final = ("consolidated", "연결")
_CLASSES: Final = {
    "보통주": "common",
    "우선주": "preferred",
    "common": "common",
    "commonstock": "common",
    "commonshares": "common",
    "preferred": "preferred",
    "preferredstock": "preferred",
    "preferredshares": "preferred",
}


def measure(label: str) -> DividendMeasure:
    """Classify a dividend row by keywords in its label.

    Args:
        label (str): Row label (``se``), English or Korean.

    Returns:
        DividendMeasure: What the row measures; ``other`` when no rule matches.
    """
    folded = " ".join(label.split()).casefold()
    for name, groups in _RULES:
        if all(any(word in folded for word in group) for group in groups):
            return name
    return "other"


def unit(label: str, kind: DividendMeasure) -> tuple[ValueUnit, int]:
    """Find a row's unit and the factor that converts filed values to it.

    Args:
        label (str): Row label, whose closing parentheses usually state the unit.
        kind (DividendMeasure): Row measure, which supplies the default unit.

    Returns:
        tuple[ValueUnit, int]: Unit of the converted values and the multiplier.
    """
    default = _UNITS[kind]
    found = _UNIT_TEXT.search(label)
    stated = fold(found.group(1)) if found else ""
    match = next(
        ((u, scale) for words, u, scale in _STATED if stated and any(w in stated for w in words)),
        None,
    )
    if match is None:
        return default
    money: ValueUnit = "KRW/share" if default[0] == "KRW/share" else "KRW"
    return match[0] or money, match[1]


def basis(label: str) -> EarningsBasis | None:
    """Read the statement basis from a label such as "(Consolidated) profit".

    Args:
        label (str): Row label.

    Returns:
        EarningsBasis | None: consolidated, separate, or None when not stated.
    """
    folded = fold(label)
    if any(word in folded for word in _SEPARATE):
        return "separate"
    return "consolidated" if any(word in folded for word in _CONSOLIDATED) else None


def share_class(value: str | None) -> str | None:
    """Name a share class in English when it is a common one.

    Args:
        value (str | None): ``stock_knd``, such as 보통주 or ``-``.

    Returns:
        str | None: common, preferred, the class as filed, or None for company totals.
    """
    cleaned = clean_text(value)
    return None if cleaned is None else _CLASSES.get(fold(cleaned), cleaned)


def value(raw: str | None, kind: ValueUnit, scale: int) -> int | float | None:
    """Convert a filed value to the row's unit.

    Args:
        raw (str | None): Filed value, such as ``1,668`` or ``25.10``.
        kind (ValueUnit): Row unit; percentages stay floats.
        scale (int): Multiplier from the filed unit.

    Returns:
        int | float | None: Whole numbers as int, others as float; None for ``-``.
    """
    number = parse_decimal(raw)
    if number is None:
        return None
    scaled = number * scale
    if kind == "%" or scaled != scaled.to_integral_value():
        return float(scaled)
    return int(scaled)


@dataclass(frozen=True, slots=True)
class DividendRow:
    """One measure for one share class across fiscal years.

    Attributes:
        measure (DividendMeasure): What the row measures.
        share_class (str | None): common, preferred, the class as filed, or None for totals.
        basis (EarningsBasis | None): Statements an earnings figure comes from, when stated.
        unit (ValueUnit): Unit of the values, converted from the filed unit.
        label (str): Label of the row as first filed, whitespace collapsed.
        values (Mapping[int, int | float]): Values by fiscal year, newest first; empty when
            every year is missing.
    """

    measure: DividendMeasure
    share_class: str | None
    basis: EarningsBasis | None
    unit: ValueUnit
    label: str
    values: Mapping[int, int | float]


@dataclass(slots=True)
class _Row:
    """A dividend row being merged across reports."""

    measure: DividendMeasure
    share_class: str | None
    basis: EarningsBasis | None
    unit: ValueUnit
    scale: int
    label: str
    values: dict[int, int | float] = field(default_factory=dict)

    def done(self) -> DividendRow:
        """Freeze the merged row, newest fiscal year first.

        Returns:
            DividendRow: The row.
        """
        values = dict(sorted(self.values.items(), reverse=True))
        return DividendRow(
            self.measure, self.share_class, self.basis, self.unit, self.label, values
        )


def _row(record: object, rows: dict[tuple[object, ...], _Row]) -> _Row:
    """Find or start the merged row a record belongs to.

    Args:
        record (object): ``alot_matter`` record.
        rows (dict[tuple[object, ...], _Row]): Rows so far, keyed by meaning.

    Returns:
        _Row: The merged row.
    """
    label = clean_text(text(record, "se")) or ""
    kind = measure(label)
    stock = share_class(text(record, "stock_knd"))
    key = (kind, stock, basis(label), label if kind == "other" else "")
    found = rows.get(key)
    if found is None:
        found = rows[key] = _Row(kind, stock, basis(label), *unit(label, kind), label)
    return found


def merge(batches: Sequence[Batch], years: range) -> tuple[DividendRow, ...]:
    """Merge rows from several annual reports; newer reports win for shared years.

    Rows with the same measure, share class, and basis merge (unrecognized rows also need the
    same label); each keeps the label and unit of its first appearance.

    Args:
        batches (Sequence[Batch]): Annual report periods with their ``alot_matter`` records,
            newest first.
        years (range): Fiscal years to keep.

    Returns:
        tuple[DividendRow, ...]: Rows in ``MEASURES`` order, then in order of first
            appearance, including rows without values.
    """
    rows: dict[tuple[object, ...], _Row] = {}
    for ref, records in batches:
        for record in records:
            row = _row(record, rows)
            for column, back in _COLUMNS:
                year = ref.fiscal_year - back
                filed = value(text(record, column), row.unit, row.scale)
                if year in years and filed is not None:
                    row.values.setdefault(year, filed)
    ordered = sorted(rows.values(), key=lambda row: MEASURES.index(row.measure))
    return tuple(row.done() for row in ordered)
