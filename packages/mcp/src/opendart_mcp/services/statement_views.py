"""Summary and full-statement views of get_financials.

``summary`` reads the major accounts (``fnltt_singl_acnt``, whose one answer holds the
consolidated and the separate rows); the full-statement views read ``fnltt_singl_acnt_all``
(one call per basis) filtered by statement type. Each view ranks its key accounts first, in
reading order, because full statements arrive sorted by account ID.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from opendart_mcp.services import derived
from opendart_mcp.services.accounts import (
    COMPONENT_ORDER,
    EQUITY_AT_END,
    KEY_ACCOUNTS,
    KEY_ACCOUNT_NAMES,
    METRICS,
    METRIC_RANK,
    TOTAL_COMPONENT,
    component,
    metric_of,
    normalize,
)
from opendart_mcp.services.periods import periodic_ttl, resolve_period
from opendart_mcp.services.statements import (
    build_report,
    column,
    filled_periods,
    full_item,
    merge,
    select,
    shift,
    summary_item,
    to_rows,
)
from opendart_mcp.services.tables import Span, Table, chain, no_data, sources

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from opendart.models.financial_statements import FnlttSinglAcntResponseListItem
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.periods import PeriodRef
    from opendart_mcp.domain.types import Basis
    from opendart_mcp.models.financials import StatementBasis
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.financials import FinancialsRequest
    from opendart_mcp.services.statements import Item, Ranker, Report
    from opendart_mcp.services.tables import Fetch

    type Scope = Literal["CFS", "OFS"]

# Statement-of-changes-in-equity ranks: component position times this span, plus the line.
_EQUITY_SPAN: Final = 10_000
_SHOW_ALL: Final = 1 << 30
_QUARTER_FLOWS: Final = "Quarterly income lines: values are three-month amounts and cumulative holds year-to-date amounts."
_YEAR_TO_DATE: Final = "Quarterly cash flows and equity changes are year-to-date amounts."
_SCOPES: Final[Mapping[str, tuple[tuple[Scope, StatementBasis], ...]]] = MappingProxyType(
    {
        "auto": (("CFS", "consolidated"), ("OFS", "separate")),
        "consolidated": (("CFS", "consolidated"),),
        "separate": (("OFS", "separate"),),
    }
)


@dataclass(frozen=True, slots=True)
class StatementSpec:
    """How a statement view selects, orders, and derives.

    Attributes:
        statements (tuple[str, ...]): Statement types to read; the first with rows wins.
        rank (Ranker): Sort position of a row given its upstream position.
        key_limit (int): Lines ranked below this are key lines in concise results.
        derive (bool): Whether derived metrics apply.
        what (str): Name of the statement, for notes.
    """

    statements: tuple[str, ...]
    rank: Ranker
    key_limit: int
    derive: bool
    what: str


def _key_rank(keys: Sequence[str], names: Mapping[str, str]) -> Ranker:
    """Rank key accounts in reading order, then other lines in upstream order.

    Args:
        keys (Sequence[str]): Key account IDs in reading order.
        names (Mapping[str, str]): Key account ID by normalized name, for lines that lack a
            standard ID.

    Returns:
        Ranker: Ranking function.
    """
    order = {account_id: rank for rank, account_id in enumerate(keys)}

    def rank(item: Item, position: int) -> int:
        """Return an account's configured position in the statement view.

        Args:
            item (Item): Reduced statement row.
            position (int): Original position in the upstream response.

        Returns:
            int: Sort position, with unlisted accounts following key accounts.
        """
        account_id = item.account_id or names.get(normalize(item.account), "")
        return order.get(account_id, len(order) + position)

    return rank


def _summary_rank(item: Item, position: int) -> int:
    """Rank summary lines: income lines, then the balance sheet, then the rest.

    Args:
        item (Item): Reduced row.
        position (int): Upstream position.

    Returns:
        int: Sort position.
    """
    metric = metric_of(item.account_id, item.account)
    return METRIC_RANK[metric.key] if metric is not None else len(METRICS) + position


def _equity_rank(item: Item, position: int) -> int:
    """Rank equity changes by component, opening balance first and closing balance last.

    Args:
        item (Item): Reduced row.
        position (int): Upstream position.

    Returns:
        int: Sort position; whole-equity lines rank below ``_EQUITY_SPAN``.
    """
    part = component(item.detail) or TOTAL_COMPONENT
    group = COMPONENT_ORDER.index(part) if part in COMPONENT_ORDER else len(COMPONENT_ORDER)
    if item.account_id in KEY_ACCOUNTS["SCE"]:
        line = 0
    elif item.account_id == EQUITY_AT_END:
        line = _EQUITY_SPAN - 1
    else:
        line = position + 1
    return group * _EQUITY_SPAN + min(line, _EQUITY_SPAN - 1)


def _spec(statements: tuple[str, ...], keys: str, *, derive: bool, what: str) -> StatementSpec:
    """Build the spec of a full-statement view ranked by key accounts.

    Args:
        statements (tuple[str, ...]): Statement types to read.
        keys (str): Statement type whose key accounts rank first.
        derive (bool): Whether derived metrics apply.
        what (str): Name of the statement.

    Returns:
        StatementSpec: View spec.
    """
    accounts = KEY_ACCOUNTS[keys]
    names = KEY_ACCOUNT_NAMES.get(keys, {})
    return StatementSpec(statements, _key_rank(accounts, names), len(accounts), derive, what)


SPECS: Final[Mapping[str, StatementSpec]] = MappingProxyType(
    {
        "summary": StatementSpec(
            ("BS", "IS"), _summary_rank, _SHOW_ALL, derive=True, what="major accounts"
        ),
        "income": _spec(("IS", "CIS"), "IS", derive=True, what="income statement"),
        "balance": _spec(("BS",), "BS", derive=True, what="balance sheet"),
        "cash_flow": _spec(("CF",), "CF", derive=False, what="cash flow statement"),
        "comprehensive_income": _spec(
            ("CIS",), "CIS", derive=False, what="statement of comprehensive income"
        ),
        "equity_changes": StatementSpec(
            ("SCE",),
            _equity_rank,
            _EQUITY_SPAN,
            derive=False,
            what="statement of changes in equity",
        ),
    }
)
"""Statement views and how each selects, orders, and derives."""


def _summary_fetch(state: AppState, company: Company) -> Fetch:
    """Bind the major-accounts fetcher for one company.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.

    Returns:
        Fetch: Fetcher of one period's major accounts on a basis.
    """

    async def fetch(ref: PeriodRef, basis: Basis) -> Report | None:
        """Fetch and select the first available major-account statement scope.

        Args:
            ref (PeriodRef): Fiscal period to fetch.
            basis (Basis): Requested statement basis.

        Returns:
            Report | None: Selected major-account report, or None when no rows are
                available.

        Raises:
            ServerError: The upstream request fails or is rejected.
        """
        gateway = state.require_gateway()
        response = await gateway.call(
            periodic_ttl(state, company, ref),
            gateway.sdk.financial_statements.fnltt_singl_acnt,
            corporation_code=company.corp_code,
            fiscal_year=str(ref.fiscal_year),
            report_period=ref.report_code,
        )
        rows: list[FnlttSinglAcntResponseListItem] = (
            (response.list or []) if response is not None else []
        )
        for scope, used in _SCOPES[basis]:
            items = [summary_item(r) for r in rows if (r.statement_scope or "").upper() == scope]
            if items:
                report = build_report(items, ref, rank=_summary_rank)
                report.basis = used
                return report
        return None

    return fetch


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


def _statement_fetch(state: AppState, company: Company, spec: StatementSpec) -> Fetch:
    """Bind the full-statement fetcher for one company and view.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        spec (StatementSpec): View spec.

    Returns:
        Fetch: Fetcher of one period's statement on a basis.
    """

    async def fetch(ref: PeriodRef, basis: Basis) -> Report | None:
        """Fetch a full statement for the requested period and basis.

        Args:
            ref (PeriodRef): Fiscal period to fetch.
            basis (Basis): Requested statement basis.

        Returns:
            Report | None: Selected statement report, or None when no rows are
                available.

        Raises:
            ServerError: The upstream request fails or is rejected.
        """
        gateway = state.require_gateway()
        ttl = periodic_ttl(state, company, ref)
        for scope, used in _SCOPES[basis]:
            response = await gateway.call(
                ttl,
                gateway.sdk.financial_statements.fnltt_singl_acnt_all,
                corporation_code=company.corp_code,
                fiscal_year=str(ref.fiscal_year),
                report_period=ref.report_code,
                statement_scope=scope,
            )
            items = [full_item(row) for row in response.list or []] if response else []
            chosen = _statement_items(items, spec.statements)
            if chosen:
                report = build_report(chosen, ref, rank=spec.rank)
                report.basis = used
                return report
        return None

    return fetch


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
    spec = SPECS[request.view]
    resolved = await resolve_period(
        state, company, period=request.period, fiscal_year=request.fiscal_year
    )
    fetch = (
        _summary_fetch(state, company)
        if request.view == "summary"
        else _statement_fetch(state, company, spec)
    )
    span = Span(years=request.years)
    found = await chain(resolved, fetch, basis=request.basis, span=span, progress=progress)
    if found is None:
        hint = (
            ' basis="auto" falls back to separate statements.'
            if request.basis == "consolidated"
            else ""
        )
        return Table(notes=[no_data(resolved, spec.what) + hint])
    merged = merge(found.reports)
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
    )
    if spec.derive:
        values = derived.metric_values(merged.lines, found.ref, shift(found.ref, 1))
        table.derived = derived.compute(values)
    table.notes = [
        *found.notes,
        *([shown] if shown else []),
        *_statement_notes(request, merged, table=table, ref=found.ref),
    ]
    return table
