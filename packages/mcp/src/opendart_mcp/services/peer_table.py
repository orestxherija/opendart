"""Lay out compare_companies' peer table: columns, one row per company, and notes.

``opendart_analysis.financials.compare_peers`` chooses the period and reads each company's
values: amount columns from the major accounts (year to date for quarterly income lines),
derived columns computed in code, and indicator columns as OpenDART publishes them. Here the
concise or detailed columns are chosen, and when both sets are shown, a derived column that
duplicates a published indicator is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.financials import derived
from opendart_analysis.financials.accounts import METRICS
from opendart_analysis.financials.indicators import (
    PERCENT_NOTE,
    key as indicator_key,
    label as indicator_label,
    rank as indicator_rank,
)
from opendart_analysis.financials.peers import DECEMBER
from opendart_analysis.financials.statements import shift
from opendart_mcp.models.compare import MissingCompany, PeerRow
from opendart_mcp.services.tables import sources

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Basis
    from opendart_analysis.financials import IndicatorValue, PeerComparison, PeerValues
    from opendart_mcp.models.common import SourceFiling
    from opendart_mcp.models.compare import ColumnUnit
    from opendart_mcp.models.financials import Number, StatementBasis
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.compare import CompareRequest

PEER_INDICATORS: Final[tuple[str, ...]] = (
    "M211300",
    "M211200",
    "M211550",
    "M212000",
    "M221100",
    "M221200",
    "M231000",
    "M231400",
    "M231800",
    "M241000",
)
"""Indicator codes a concise peer table shows."""
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
    order = sorted(names, key=lambda code: indicator_rank(code, list(names).index(code)))
    codes = order if detailed else [code for code in PEER_INDICATORS if code in names]
    found = [
        Column(indicator_key(code), indicator_label(code, names[code]), "pct", "indicator", code)
        for code in codes
    ]
    taken = {column.key for column in found}
    return [column for column in columns if column.key not in taken] + found


def _missing_reason(*, filed: bool, ref: PeriodRef, basis: Basis) -> str:
    """Explain why a company has no account values.

    Args:
        filed (bool): Whether the company filed major accounts on any basis.
        ref (PeriodRef): Period.
        basis (Basis): Requested basis.

    Returns:
        str: Reason for the missing list.
    """
    if filed:
        return f'No {basis} statements for {ref.label}; pass basis="auto".'
    return f"No {ref.label} data in OpenDART (not filed yet, or not covered)."


def row(
    company: Company,
    peer: PeerValues,
    *,
    ref: PeriodRef,
    columns: Sequence[Column],
    request: CompareRequest,
) -> PeerRow | str:
    """Build one company's row, or explain why it has none.

    Args:
        company (Company): Company.
        peer (PeerValues): The company's values for the compared period.
        ref (PeriodRef): Compared period.
        columns (Sequence[Column]): Table columns.
        request (CompareRequest): Request.

    Returns:
        PeerRow | str: Row, or the reason the company is missing.
    """
    values: Mapping[str, Number | None] = {}
    used: StatementBasis | None = None
    if request.metrics != "ratios":
        if peer.accounts is None:
            return _missing_reason(filed=peer.filed, ref=ref, basis=request.basis)
        used, values = peer.basis, peer.accounts
    elif not any(value is not None for value in peer.indicators.values()):
        return f"No {ref.label} indicators in OpenDART."
    cells = [
        peer.indicators.get(column.code) if column.source == "indicator" else values.get(column.key)
        for column in columns
    ]
    detailed = request.response_format == "detailed"
    shown = company.ref if detailed else company.ref.model_copy(update={"korean_name": None})
    return PeerRow(
        company=shown, values=cells, basis_used=used if request.basis == "auto" else None
    )


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
    companies: Sequence[Company],
    built: Built,
    comparison: PeerComparison,
    *,
    request: CompareRequest,
) -> list[str]:
    """Explain the period chosen, derived formulas, units, and fiscal-year differences.

    Args:
        companies (Sequence[Company]): Resolved companies.
        built (Built): Table built so far.
        comparison (PeerComparison): Compared period and its coverage.
        request (CompareRequest): Request.

    Returns:
        list[str]: Notes.
    """
    ref = comparison.ref
    notes: list[str] = []
    if ref != comparison.newest or comparison.coverage < len(companies):
        notes.append(
            f"{ref.label} is the newest period with data for the most companies ({comparison.coverage} of {len(companies)})."
        )
    keys = [column.key for column in built.columns if column.source == "derived"]
    formula = derived.note(keys, period=ref.label, comparison=shift(ref, 1).label)
    notes += [formula] if formula else []
    if ref.period != "FY" and request.metrics != "ratios":
        notes.append("Quarterly income amounts are year to date.")
    if any(column.source == "indicator" for column in built.columns):
        notes.append(PERCENT_NOTE)
    offset = [c.ref.name for c in companies if c.fye_month != DECEMBER]
    if offset:
        notes.append(
            f"Fiscal years not ending in December: {", ".join(offset)}; their {ref.label} covers a different span."
        )
    separate = [row.company.name for row in built.rows if row.basis_used == "separate"]
    if separate:
        notes.append(f"Separate statements used for: {", ".join(separate)}.")
    return notes


def build(
    companies: Sequence[Company], comparison: PeerComparison, *, request: CompareRequest
) -> Built:
    """Lay out the peer table for compared companies.

    Args:
        companies (Sequence[Company]): Companies, aligned with ``comparison.peers``.
        comparison (PeerComparison): Values per company for the compared period.
        request (CompareRequest): Request.

    Returns:
        Built: Columns, rows, missing companies, notes, and filings.
    """
    chosen = columns(request, comparison.indicators)
    built = Built(chosen, [], [], list(comparison.notes), [])
    for company, peer in zip(companies, comparison.peers, strict=True):
        made = row(company, peer, ref=comparison.ref, columns=chosen, request=request)
        if isinstance(made, str):
            built.missing.append(MissingCompany(company=company.ref.name, reason=made))
            continue
        built.rows.append(made)
        cited = [*(f.filing_number for f in built.filings), *peer.filings[:1]]
        built.filings = sources(cited, None)
    built.notes += notes(companies, built, comparison, request=request)
    return built
