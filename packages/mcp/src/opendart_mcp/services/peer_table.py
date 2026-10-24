"""Lay out compare_companies' peer table: columns, one row per company, and notes.

Amount columns come from the major accounts (year to date for quarterly income lines),
derived columns are computed in code, and indicator columns are OpenDART's published values.
When both sets are shown, a derived column that duplicates a published indicator is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from opendart_mcp.models.compare import PeerRow
from opendart_mcp.services import derived, ratios
from opendart_mcp.services.accounts import METRICS
from opendart_mcp.services.statements import build_report, shift, summary_item

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from opendart.models.financial_statements import FnlttMultiAcntResponseListItem
    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Basis
    from opendart_mcp.models.common import SourceFiling
    from opendart_mcp.models.compare import ColumnUnit, MissingCompany
    from opendart_mcp.models.financials import Number, StatementBasis
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.compare import CompareRequest, Probe
    from opendart_mcp.services.ratios import IndicatorValue

DECEMBER: Final = 12
_ACCOUNTS: Final = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
)
_DERIVED: Final = ("revenue_growth", "operating_margin", "net_margin", "debt_to_equity")
_DERIVED_LABELS: Final = {
    "revenue_growth": "Revenue growth (derived)",
    "operating_income_growth": "Operating profit growth (derived)",
    "net_income_growth": "Net profit growth (derived)",
    "operating_margin": "Operating margin (derived)",
    "net_margin": "Net margin (derived)",
    "debt_to_equity": "Debt-to-equity (derived)",
    "current_ratio": "Current ratio (derived)",
}
_SCOPES: Final = {"consolidated": "CFS", "separate": "OFS"}


@dataclass(frozen=True, slots=True)
class Column:
    """A metric column and where its values come from.

    Attributes:
        key (str): Column key.
        label (str): Column label.
        unit (ColumnUnit): krw or pct.
        source (Literal["account", "derived", "indicator"]): Value source.
        code (str): Indicator code, for indicator columns.
    """

    key: str
    label: str
    unit: ColumnUnit
    source: Literal["account", "derived", "indicator"]
    code: str = ""


def columns(request: CompareRequest, indicators: Sequence[IndicatorValue]) -> list[Column]:
    """Choose the table's columns.

    Args:
        request (CompareRequest): Request.
        indicators (Sequence[IndicatorValue]): Indicator values fetched, if any.

    Returns:
        list[Column]: Columns in display order.
    """
    detailed = request.response_format == "detailed"
    columns: list[Column] = []
    if request.metrics != "ratios":
        keys = [metric.key for metric in METRICS] if detailed else list(_ACCOUNTS)
        labels = {metric.key: metric.label for metric in METRICS}
        columns += [Column(key, labels[key], "krw", "account") for key in keys]
        extra = [key for key in _DERIVED_LABELS if detailed or key in _DERIVED]
        columns += [Column(key, _DERIVED_LABELS[key], "pct", "derived") for key in extra]
    if request.metrics == "key_accounts":
        return columns
    names = {value.code: value.name for value in reversed(indicators)}
    order = sorted(names, key=lambda code: ratios.rank(code, list(names).index(code)))
    codes = order if detailed else [code for code in ratios.PEER_INDICATORS if code in names]
    found = [
        Column(ratios.key(code), ratios.label(code, names[code]), "pct", "indicator", code)
        for code in codes
    ]
    taken = {column.key for column in found}
    return [column for column in columns if column.key not in taken] + found


def _choose(
    rows: Sequence[FnlttMultiAcntResponseListItem], basis: Basis
) -> tuple[StatementBasis, list[FnlttMultiAcntResponseListItem]] | None:
    """Pick one company's rows for the requested basis.

    Args:
        rows (Sequence[FnlttMultiAcntResponseListItem]): The company's rows, both bases.
        basis (Basis): Requested basis; auto prefers consolidated.

    Returns:
        tuple[StatementBasis, list[FnlttMultiAcntResponseListItem]] | None: Basis used and
            rows, or None when the basis is not filed.
    """
    order: tuple[StatementBasis, ...] = (
        ("consolidated", "separate") if basis == "auto" else (basis,)
    )
    for used in order:
        chosen = [row for row in rows if (row.statement_scope or "").upper() == _SCOPES[used]]
        if chosen:
            return used, chosen
    return None


def _account_values(
    rows: Sequence[FnlttMultiAcntResponseListItem], ref: PeriodRef
) -> dict[str, Number | None]:
    """Read key accounts (year to date for quarterly income) and derived metrics.

    Args:
        rows (Sequence[FnlttMultiAcntResponseListItem]): One company's rows on one basis.
        ref (PeriodRef): Period.

    Returns:
        dict[str, Number | None]: Values by column key.
    """
    report = build_report(
        [summary_item(row) for row in rows], ref, rank=lambda _, position: position
    )
    pairs = derived.metric_values(report.lines, ref, shift(ref, 1))
    return {**{key: pair[0] for key, pair in pairs.items()}, **derived.compute(pairs)}


def _missing_reason(rows: Sequence[object], ref: PeriodRef, basis: Basis) -> str:
    """Explain why a company has no account values.

    Args:
        rows (Sequence[object]): The company's rows on any basis.
        ref (PeriodRef): Period.
        basis (Basis): Requested basis.

    Returns:
        str: Reason for the missing list.
    """
    if rows:
        return f'No {basis} statements for {ref.label}; pass basis="auto".'
    return f"No {ref.label} data in OpenDART (not filed yet, or not covered)."


def row(
    company: Company,
    probe: Probe,
    indicators: Mapping[str, float | None],
    *,
    columns: Sequence[Column],
    request: CompareRequest,
) -> PeerRow | str:
    """Build one company's row, or explain why it has none.

    Args:
        company (Company): Company.
        probe (Probe): Chosen period and major-account rows.
        indicators (Mapping[str, float | None]): The company's indicator values by code.
        columns (Sequence[Column]): Table columns.
        request (CompareRequest): Request.

    Returns:
        PeerRow | str: Row, or the reason the company is missing.
    """
    values: dict[str, Number | None] = {}
    used: StatementBasis | None = None
    if request.metrics != "ratios":
        rows = probe.rows.get(company.corp_code, [])
        chosen = _choose(rows, request.basis)
        if chosen is None:
            return _missing_reason(rows, probe.ref, request.basis)
        used, picked = chosen
        values = _account_values(picked, probe.ref)
    elif not any(value is not None for value in indicators.values()):
        return f"No {probe.ref.label} indicators in OpenDART."
    cells = [
        indicators.get(column.code) if column.source == "indicator" else values.get(column.key)
        for column in columns
    ]
    detailed = request.response_format == "detailed"
    ref = company.ref if detailed else company.ref.model_copy(update={"korean_name": None})
    return PeerRow(company=ref, values=cells, basis_used=used if request.basis == "auto" else None)


@dataclass(slots=True)
class Built:
    """A peer table before the result envelope.

    Attributes:
        columns (list[Column]): Columns.
        rows (list[PeerRow]): Rows.
        missing (list[MissingCompany]): Companies without data.
        notes (list[str]): Notes.
        filings (list[SourceFiling]): Filings the rows come from.
    """

    columns: list[Column]
    rows: list[PeerRow]
    missing: list[MissingCompany]
    notes: list[str]
    filings: list[SourceFiling]


def notes(
    companies: Sequence[Company], built: Built, probe: Probe, *, request: CompareRequest
) -> list[str]:
    """Explain the period chosen, derived formulas, units, and fiscal-year differences.

    Args:
        companies (Sequence[Company]): Resolved companies.
        built (Built): Table built so far.
        probe (Probe): Chosen period.
        request (CompareRequest): Request.

    Returns:
        list[str]: Notes.
    """
    ref = probe.ref
    notes: list[str] = []
    if ref != probe.newest or probe.coverage < len(companies):
        notes.append(
            f"{ref.label} is the newest period with data for the most companies ({probe.coverage} of {len(companies)})."
        )
    keys = [column.key for column in built.columns if column.source == "derived"]
    formula = derived.note(keys, period=ref.label, comparison=shift(ref, 1).label)
    notes += [formula] if formula else []
    if ref.period != "FY" and request.metrics != "ratios":
        notes.append("Quarterly income amounts are year to date.")
    if any(column.source == "indicator" for column in built.columns):
        notes.append(ratios.PERCENT_NOTE)
    offset = [c.ref.name for c in companies if c.fye_month != DECEMBER]
    if offset:
        notes.append(
            f"Fiscal years not ending in December: {", ".join(offset)}; their {ref.label} covers a different span."
        )
    separate = [row.company.name for row in built.rows if row.basis_used == "separate"]
    if separate:
        notes.append(f"Separate statements used for: {", ".join(separate)}.")
    return notes
