"""get_dividends: dividend history by share class from annual reports.

``alot_matter`` returns one row per measure and share class with values for three fiscal
years: current (``thstrm``), prior (``frmtrm``), and two years prior (``lwfr``). The English
service labels rows in English with the unit in parentheses, such as "Cash dividend per
share (KRW)" or "Total cash dividends (KRW million)", while share classes stay Korean
(보통주 common, 우선주 preferred) and ``-`` marks a missing value. Rows are classified by
keywords in either language, totals filed in KRW million become won, and histories longer
than three years chain earlier annual reports, one call per three fiscal years.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.normalize import clean_text, parse_decimal
from opendart_analysis.domain.periods import fiscal_years_back
from opendart_mcp.core.progress import no_progress
from opendart_mcp.models.dividends import DividendRow, DividendsResult
from opendart_mcp.services.extracts import (
    checked,
    fetch_records,
    fold,
    gather_all,
    probe_attempts,
    sources,
    text,
)
from opendart_mcp.services.periods import first_available, resolve_period

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.models.dividends import DividendMeasure, EarningsBasis, ValueUnit
    from opendart_mcp.services.companies import Company

    type Batch = tuple[PeriodRef, Sequence[object]]

SERVICE: Final = "alot_matter"
YEARS_PER_REPORT: Final = 3
YIELD_NOTE: Final = "Yields are as filed, computed by the company from its own reference price; OpenDART has no market prices, so they are not recomputed."

_COLUMNS: Final = (("thstrm", 0), ("frmtrm", 1), ("lwfr", 2))
_ORDER: Final[tuple[DividendMeasure, ...]] = (
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

    def output(self, *, detailed: bool) -> DividendRow:
        """Convert to the output row.

        Args:
            detailed (bool): Whether to keep the label as filed.

        Returns:
            DividendRow: Row with values by fiscal year, newest first.
        """
        return DividendRow(
            measure=self.measure,
            share_class=self.share_class,
            basis=self.basis,
            unit=self.unit,
            values_by_year={str(y): v for y, v in sorted(self.values.items(), reverse=True)},
            label=self.label if detailed or self.measure == "other" else None,
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


def merge(batches: Sequence[Batch], years: range) -> list[_Row]:
    """Merge rows from several annual reports; newer reports win for shared years.

    Args:
        batches (Sequence[Batch]): Report periods with their records, newest first.
        years (range): Fiscal years to keep.

    Returns:
        list[_Row]: Rows by measure, dividends first, then in order of first appearance.
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
    return sorted(rows.values(), key=lambda row: _ORDER.index(row.measure))


async def _history(
    state: AppState, company: Company, newest: Batch, *, years: int
) -> tuple[list[Batch], list[PeriodRef]]:
    """Fetch the earlier annual reports a history needs.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        newest (Batch): Newest annual report with data.
        years (int): Fiscal years requested.

    Returns:
        tuple[list[Batch], list[PeriodRef]]: Reports with data, newest first, and the
            periods that had none.
    """
    calls = math.ceil(years / YEARS_PER_REPORT)
    refs = fiscal_years_back(newest[0], calls, step=YEARS_PER_REPORT)[1:]
    found = await gather_all(fetch_records(state, SERVICE, company=company, ref=r) for r in refs)
    batches = [newest, *((r, rows) for r, rows in zip(refs, found, strict=True) if rows)]
    return batches, [r for r, rows in zip(refs, found, strict=True) if rows is None]


def _notes(rows: Sequence[DividendRow], missing: Sequence[PeriodRef]) -> list[str]:
    """Explain gaps and how yields were computed.

    Args:
        rows (Sequence[DividendRow]): Output rows.
        missing (Sequence[PeriodRef]): Annual reports without dividend data.

    Returns:
        list[str]: Notes.
    """
    notes = []
    if missing:
        labels = ", ".join(ref.label for ref in missing)
        notes.append(f"No dividend table for {labels}; earlier years are missing.")
    if any(row.measure in {"cash_yield", "stock_yield"} and row.values_by_year for row in rows):
        notes.append(YIELD_NOTE)
    return notes


async def dividends(
    state: AppState,
    company: str,
    *,
    years: int = 3,
    response_format: ResponseFormat = "concise",
    progress: Progress = no_progress,
) -> DividendsResult:
    """Build a company's dividend history from its annual reports.

    Args:
        state (AppState): Server state.
        company (str): Name, stock code, or corp code.
        years (int): Fiscal years of history, newest first; three per upstream call.
        response_format (ResponseFormat): ``detailed`` adds par value, empty rows, and
            labels as filed.
        progress (Progress): Reports progress.

    Returns:
        DividendsResult: Rows by measure and share class, or an empty result with a note.
    """
    resolved_company = await state.companies.resolve(company, progress=progress)
    resolved = await resolve_period(state, resolved_company, period="FY", fiscal_year=None)
    await progress(f"Reading dividends for {resolved_company.ref.name}")
    found = await first_available(
        resolved,
        lambda ref: fetch_records(state, SERVICE, company=resolved_company, ref=ref),
        attempts=probe_attempts(resolved),
    )
    if found is None:
        note = f"OpenDART has no dividend table in {checked(resolved)}."
        return DividendsResult(company=resolved_company.ref, notes=[note], as_of=state.today())
    batches, missing = await _history(state, resolved_company, found, years=years)
    newest = found[0].fiscal_year
    detailed = response_format == "detailed"
    merged = merge(batches, range(newest - years + 1, newest + 1))
    rows = [
        row.output(detailed=detailed)
        for row in merged
        if detailed or (row.values and row.measure != "par_value")
    ]
    numbers = (text(record, "filing_number") for _, records in batches for record in records)
    return DividendsResult(
        company=resolved_company.ref,
        as_of=state.today(),
        source_filings=sources(numbers, resolved.report),
        notes=_notes(rows, missing),
        fiscal_years=sorted({year for row in merged for year in row.values}, reverse=True),
        rows=rows,
    )
