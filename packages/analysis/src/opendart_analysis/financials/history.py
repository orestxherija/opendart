"""Statement history: one company's major accounts or a full statement over periods.

A workflow takes a company and its ``ResolvedPeriod`` (from
``opendart_analysis.reports.resolve_period``), probes the candidate periods for the newest
one with data, chains earlier reports for more years, merges them with newer reports winning,
and computes derived metrics. ``basis="auto"`` prefers consolidated statements and falls back
to separate ones; chained reports keep the basis the newest one used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opendart_analysis.financials import derived
from opendart_analysis.financials.access import StatementQuery
from opendart_analysis.financials.chain import Span, chain, check_reports
from opendart_analysis.financials.specs import SCOPES, STATEMENTS, summary_rank
from opendart_analysis.financials.statements import (
    build_report,
    full_item,
    merge,
    scope_rows,
    shift,
    summary_item,
)
from opendart_analysis.reports import period_volatility
from opendart_analysis.reports.query import ReportQuery
from opendart_analysis.upstream import no_progress

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Basis
    from opendart_analysis.financials.access import FetchFullStatements, FetchMajorAccounts
    from opendart_analysis.financials.chain import FetchReport
    from opendart_analysis.financials.specs import FullStatement, StatementSpec
    from opendart_analysis.financials.statements import Item, Report
    from opendart_analysis.reports import FiscalCompany, ResolvedPeriod
    from opendart_analysis.upstream import Progress


@dataclass(frozen=True, slots=True)
class HistoryRequest:
    """How many reports to chain and on which basis.

    Attributes:
        basis (Basis): ``auto`` prefers consolidated statements and falls back to separate.
        years (int): Reports to chain, newest first, 1 to ``MAX_REPORTS``; one annual report
            covers three fiscal years.
    """

    basis: Basis = "auto"
    years: int = 1

    def __post_init__(self) -> None:
        """Reject a report count outside the acquisition bound.

        Raises:
            ValueError: ``years`` is outside 1 to ``MAX_REPORTS``.
        """
        check_reports(self.years)


@dataclass(frozen=True, slots=True)
class StatementRequest:
    """Which full statement to read, how many reports to chain, and on which basis.

    Attributes:
        statement (FullStatement): Statement, such as ``income`` or ``balance``.
        basis (Basis): ``auto`` prefers consolidated statements and falls back to separate.
        years (int): Reports to chain, newest first, 1 to ``MAX_REPORTS``.
    """

    statement: FullStatement
    basis: Basis = "auto"
    years: int = 1

    def __post_init__(self) -> None:
        """Reject a report count outside the acquisition bound.

        Raises:
            ValueError: ``years`` is outside 1 to ``MAX_REPORTS``.
        """
        check_reports(self.years)


@dataclass(frozen=True, slots=True)
class StatementHistory:
    """Line items over periods, merged from the newest report backwards.

    Attributes:
        ref (PeriodRef): Newest period with data.
        report (Report): Merged lines with their filings, basis, and currency.
        derived (Mapping[str, float]): Growth, margins, and leverage in percent, computed from
            reported amounts for ``ref`` (year to date in quarterly reports); empty where
            derived metrics do not apply.
        notes (tuple[str, ...]): Period fallbacks and earlier periods without data.
    """

    ref: PeriodRef
    report: Report
    derived: Mapping[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


def _statement_items(items: Sequence[Item], statements: Sequence[str]) -> list[Item]:
    """Keep the rows of the first statement type that has any.

    Args:
        items (Sequence[Item]): Reduced rows of every statement.
        statements (Sequence[str]): Statement types in order of preference.

    Returns:
        list[Item]: Rows of one statement type, or none.
    """
    for statement in statements:
        chosen = [item for item in items if item.statement == statement]
        if chosen:
            return chosen
    return []


async def _history(
    resolved: ResolvedPeriod,
    fetch: FetchReport,
    *,
    spec: StatementSpec,
    request: HistoryRequest | StatementRequest,
    progress: Progress | None,
) -> StatementHistory | None:
    """Chain, merge, and derive.

    Args:
        resolved (ResolvedPeriod): Candidate periods.
        fetch (FetchReport): Fetches one period's report on a basis.
        spec (StatementSpec): Statement spec.
        request (HistoryRequest | StatementRequest): Basis and reports wanted.
        progress (Progress | None): Receives one message per report fetched.

    Returns:
        StatementHistory | None: The history, or None when no candidate period has data.
    """
    span = Span(years=request.years)
    found = await chain(
        resolved, fetch, basis=request.basis, span=span, progress=progress or no_progress
    )
    if found is None:
        return None
    merged = merge(found.reports)
    metrics: dict[str, float] = {}
    if spec.derive:
        metrics = derived.compute(
            derived.metric_values(merged.lines, found.ref, shift(found.ref, 1))
        )
    return StatementHistory(found.ref, merged, metrics, found.notes)


async def major_accounts(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    request: HistoryRequest,
    fetch_major_accounts: FetchMajorAccounts,
    today: date,
    progress: Progress | None = None,
) -> StatementHistory | None:
    """Read a company's major accounts (the summary statements) over periods.

    Makes one call per report: at most three candidate periods, then ``request.years - 1``
    earlier reports. Lines rank income lines first, then the balance sheet.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        request (HistoryRequest): Basis and reports wanted.
        fetch_major_accounts (FetchMajorAccounts): Major accounts of one period; asked with
            ``period_volatility`` of that period.
        today (date): Today in KST, which sets each period's volatility.
        progress (Progress | None): Receives one message per report fetched.

    Returns:
        StatementHistory | None: Lines with derived metrics, or None when no candidate period
            has data on the requested basis.
    """

    async def fetch(ref: PeriodRef, basis: Basis) -> Report | None:
        """Fetch one period and keep the first basis that has rows.

        Args:
            ref (PeriodRef): Period to fetch.
            basis (Basis): Requested basis.

        Returns:
            Report | None: The report, or None when no basis has rows.
        """
        volatility = period_volatility(ref, fye_month=company.fye_month, today=today)
        query = ReportQuery.of(company.corp_code, ref)
        rows = await fetch_major_accounts(query, volatility=volatility) or ()
        for scope, used in SCOPES[basis]:
            items = [summary_item(row) for row in scope_rows(rows, scope)]
            if items:
                return build_report(items, ref, rank=summary_rank, basis=used)
        return None

    spec = STATEMENTS["summary"]
    return await _history(resolved, fetch, spec=spec, request=request, progress=progress)


async def financial_statement(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    request: StatementRequest,
    fetch_full_statements: FetchFullStatements,
    today: date,
    progress: Progress | None = None,
) -> StatementHistory | None:
    """Read one of a company's full statements over periods.

    Makes one call per report and basis tried: at most three candidate periods, then
    ``request.years - 1`` earlier reports on the basis the newest one used. The income view
    falls back to a single statement of comprehensive income when no income statement is
    filed. Key accounts come first, in reading order.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        request (StatementRequest): Statement, basis, and reports wanted.
        fetch_full_statements (FetchFullStatements): Full statements of one period and basis;
            asked with ``period_volatility`` of that period.
        today (date): Today in KST, which sets each period's volatility.
        progress (Progress | None): Receives one message per report fetched.

    Returns:
        StatementHistory | None: Lines (with derived metrics for the income statement and
            balance sheet), or None when no candidate period has data on the requested basis.
    """
    spec = STATEMENTS[request.statement]

    async def fetch(ref: PeriodRef, basis: Basis) -> Report | None:
        """Fetch one period, trying each basis in order until the statement has rows.

        Args:
            ref (PeriodRef): Period to fetch.
            basis (Basis): Requested basis.

        Returns:
            Report | None: The report, or None when no basis has the statement.
        """
        volatility = period_volatility(ref, fye_month=company.fye_month, today=today)
        for scope, used in SCOPES[basis]:
            query = StatementQuery(company.corp_code, ref.fiscal_year, ref.report_code, scope)
            rows = await fetch_full_statements(query, volatility=volatility)
            chosen = _statement_items([full_item(row) for row in rows or ()], spec.statements)
            if chosen:
                return build_report(chosen, ref, rank=spec.rank, basis=used)
        return None

    return await _history(resolved, fetch, spec=spec, request=request, progress=progress)
