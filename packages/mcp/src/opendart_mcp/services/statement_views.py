"""Summary and full-statement views of get_financials.

``opendart_analysis.financials`` reads the major accounts (``summary``) or a full statement
over periods, merges restatements, and derives metrics; this adapter binds its data access
to the gateway, then chooses the lines a concise result shows, lays them out as the output
model's columns and rows, and explains fallbacks, quarterly amounts, and currencies.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final, get_args

from opendart_analysis.financials import derived
from opendart_analysis.financials.history import (
    HistoryRequest,
    StatementRequest,
    financial_statement,
    major_accounts,
)
from opendart_analysis.financials.specs import STATEMENTS, FullStatement
from opendart_analysis.financials.statements import filled_periods, shift
from opendart_mcp.core.upstream_financials import full_statements_fetch, major_accounts_fetch
from opendart_mcp.services.periods import resolve_period
from opendart_mcp.services.statements import column, select, to_rows
from opendart_mcp.services.tables import Table, no_data, sources

if TYPE_CHECKING:
    from collections.abc import Mapping

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.financials import Report, StatementHistory
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.financials import FinancialsRequest
    from opendart_mcp.services.periods import ResolvedPeriod

_QUARTER_FLOWS: Final = "Quarterly income lines: values are three-month amounts and cumulative holds year-to-date amounts."
_YEAR_TO_DATE: Final = "Quarterly cash flows and equity changes are year-to-date amounts."
_FULL: Final[Mapping[str, FullStatement]] = MappingProxyType(
    {statement: statement for statement in get_args(FullStatement)}
)


def _statement_notes(
    request: FinancialsRequest, merged: Report, *, table: Table, ref: PeriodRef
) -> list[str]:
    """Explain fallbacks, quarterly amounts, currency, and derived metrics.

    Args:
        request (FinancialsRequest): Request.
        merged (Report): Merged report.
        table (Table): Table built so far.
        ref (PeriodRef): Newest period.

    Returns:
        list[str]: Notes in reading order.
    """
    notes: list[str] = []
    if request.basis == "auto" and merged.basis == "separate":
        notes.append(
            f"No consolidated statements are filed for {ref.label}; showing separate statements."
        )
    if request.view == "income" and not any(line.key.startswith("IS:") for line in merged.lines):
        notes.append("The company presents a single statement of comprehensive income; showing it.")
    if any(row.cumulative for row in table.rows):
        notes.append(_QUARTER_FLOWS)
    if ref.period != "FY" and request.view in {"cash_flow", "equity_changes"}:
        notes.append(_YEAR_TO_DATE)
    if merged.currency != "KRW":
        notes.append(
            f"Amounts are in {merged.currency}, not won; the unit labels refer to that currency."
        )
    year_to_date = ref.period != "FY" and not derived.INCOME_KEYS.isdisjoint(table.derived)
    span = f"{ref.label} (year to date)" if year_to_date else ref.label
    formula = derived.note(table.derived, period=span, comparison=shift(ref, 1).label)
    return [*notes, *([formula] if formula else [])]


async def _history(
    state: AppState,
    company: Company,
    resolved: ResolvedPeriod,
    *,
    request: FinancialsRequest,
    progress: Progress,
) -> StatementHistory | None:
    """Read the requested statement over periods through the gateway.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        resolved (ResolvedPeriod): Candidate periods.
        request (FinancialsRequest): Request; its view is summary or a full statement.
        progress (Progress): Progress callback.

    Returns:
        StatementHistory | None: Lines by period, or None when no candidate has data.
    """
    if request.view == "summary":
        return await major_accounts(
            company,
            resolved,
            request=HistoryRequest(basis=request.basis, years=request.years),
            fetch_major_accounts=major_accounts_fetch(state.require_gateway),
            today=state.today(),
            progress=progress,
        )
    return await financial_statement(
        company,
        resolved,
        request=StatementRequest(_FULL[request.view], basis=request.basis, years=request.years),
        fetch_full_statements=full_statements_fetch(state.require_gateway),
        today=state.today(),
        progress=progress,
    )


async def statements_view(
    state: AppState, company: Company, *, request: FinancialsRequest, progress: Progress
) -> Table:
    """Build the summary or a full-statement view.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        request (FinancialsRequest): Request.
        progress (Progress): Progress callback.

    Returns:
        Table: Lines by period with derived metrics and notes.
    """
    spec = STATEMENTS["summary" if request.view == "summary" else _FULL[request.view]]
    resolved = await resolve_period(
        state, company, period=request.period, fiscal_year=request.fiscal_year
    )
    found = await _history(state, company, resolved, request=request, progress=progress)
    if found is None:
        hint = (
            ' basis="auto" falls back to separate statements.'
            if request.basis == "consolidated"
            else ""
        )
        return Table(notes=[no_data(resolved, spec.name) + hint])
    merged = found.report
    lines, shown = select(
        merged.lines, accounts=request.accounts, detailed=request.detailed, key_limit=spec.key_limit
    )
    periods = filled_periods(lines)
    table = Table(
        periods=[column(ref, fye_month=company.fye_month) for ref in periods],
        rows=to_rows(lines, periods, detailed=request.detailed),
        filings=sources(merged.filings, resolved.report),
        basis=merged.basis,
        currency=merged.currency,
        derived=dict(found.derived),
    )
    table.notes = [
        *found.notes,
        *([shown] if shown else []),
        *_statement_notes(request, merged, table=table, ref=found.ref),
    ]
    return table
