"""get_financials: every statement view of one company as line items by periods.

The summary and full-statement views live in ``statement_views``; this module adds the
indicator, equity-investment, and preliminary-earnings views and dispatches requests.
``basis="auto"`` prefers consolidated statements and says so when it falls back.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

from opendart_analysis.domain.periods import FIRST_INDICATOR_YEAR
from opendart_analysis.errors import AnalysisError
from opendart_analysis.financials.chain import fallback_note
from opendart_analysis.financials.indicators import KEY_INDICATORS, PERCENT_NOTE, indicator_history
from opendart_analysis.financials.investments import latest_holdings
from opendart_analysis.financials.statements import filled_periods
from opendart_mcp.core.errors import InvalidArgumentError, from_analysis
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream_financials import indicators_fetch, investments_fetch
from opendart_mcp.models.financials import FinancialsResult
from opendart_mcp.services.investments import holdings_table
from opendart_mcp.services.periods import resolve_period
from opendart_mcp.services.preliminary import latest_preliminary
from opendart_mcp.services.preliminary_table import preliminary_table
from opendart_mcp.services.statement_views import statements_view
from opendart_mcp.services.statements import column, select, to_rows
from opendart_mcp.services.tables import Table, no_data, sources

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

    from opendart_analysis.domain.types import Basis, Period, Unit
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.models.financials import FinancialView
    from opendart_mcp.services.companies import Company


@dataclass(frozen=True, slots=True)
class FinancialsRequest:
    """What get_financials was asked for.

    Attributes:
        view (FinancialView): Statement view.
        basis (Basis): Requested basis.
        period (Period): Requested period.
        fiscal_year (int | None): Requested fiscal year.
        years (int): Reports to chain backwards.
        accounts (tuple[str, ...] | None): Substring filters on account names.
        unit (Unit): Display unit of the text table.
        response_format (ResponseFormat): Concise or detailed.
    """

    view: FinancialView = "summary"
    basis: Basis = "auto"
    period: Period = "latest"
    fiscal_year: int | None = None
    years: int = 1
    accounts: tuple[str, ...] | None = None
    unit: Unit = "million_krw"
    response_format: ResponseFormat = "concise"

    @property
    def detailed(self) -> bool:
        """Whether every line and field is wanted.

        Returns:
            bool: True for the detailed format.
        """
        return self.response_format == "detailed"


class _View(Protocol):
    """A view builder: one company and request in, one table out."""

    def __call__(
        self, state: AppState, company: Company, *, request: FinancialsRequest, progress: Progress
    ) -> Awaitable[Table]:
        """Build a financial view for one company.

        Args:
            state (AppState): Server state.
            company (Company): Resolved company.
            request (FinancialsRequest): Request.
            progress (Progress): Progress callback.

        Returns:
            Awaitable[Table]: Awaitable producing the requested table.
        """


async def _ratios(
    state: AppState, company: Company, *, request: FinancialsRequest, progress: Progress
) -> Table:
    """Build the indicators view, one column per fiscal year.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        request (FinancialsRequest): Request.
        progress (Progress): Progress callback.

    Returns:
        Table: Indicators by period.

    Raises:
        InvalidArgumentError: The requested fiscal year predates OpenDART's indicators.
    """
    if request.fiscal_year is not None and request.fiscal_year < FIRST_INDICATOR_YEAR:
        message = f'OpenDART publishes financial indicators from fiscal {FIRST_INDICATOR_YEAR}; pass fiscal_year={FIRST_INDICATOR_YEAR} or later, or use view="summary" for derived margins and leverage.'
        raise InvalidArgumentError(message)
    resolved = await resolve_period(
        state, company, period=request.period, fiscal_year=request.fiscal_year
    )
    try:
        found = await indicator_history(
            company,
            resolved,
            years=request.years,
            fetch_indicators=indicators_fetch(state.require_gateway),
            today=state.today(),
            progress=progress,
        )
    except AnalysisError as error:
        raise from_analysis(error) from error
    if found is None:
        return Table(notes=[no_data(resolved, "financial indicators")])
    merged = found.report
    lines, shown = select(
        merged.lines,
        accounts=request.accounts,
        detailed=request.detailed,
        key_limit=len(KEY_INDICATORS),
    )
    periods = filled_periods(lines)
    report = resolved.report
    cited = [report.filing_number] if report is not None and report.ref == found.ref else []
    notes = [*found.notes, PERCENT_NOTE, *([shown] if shown else [])]
    if request.basis != "auto":
        notes.append(
            "OpenDART does not state the basis of its indicators, so basis does not apply."
        )
    return Table(
        periods=[column(ref, fye_month=company.fye_month) for ref in periods],
        rows=to_rows(lines, periods, detailed=request.detailed),
        notes=notes,
        filings=sources(cited, report),
    )


async def _investments(
    state: AppState, company: Company, *, request: FinancialsRequest, progress: Progress
) -> Table:
    """Build the equity-investments view: book values by period plus the holdings.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        request (FinancialsRequest): Request.
        progress (Progress): Progress callback.

    Returns:
        Table: Holdings with closing and opening book values.
    """
    resolved = await resolve_period(
        state, company, period=request.period, fiscal_year=request.fiscal_year
    )
    holdings = await latest_holdings(
        company,
        resolved,
        fetch_investments=investments_fetch(state.require_gateway),
        today=state.today(),
        progress=progress,
    )
    if holdings is None:
        return Table(notes=[no_data(resolved, "equity investment table")])
    ref = holdings.ref
    periods, rows, investments, shown = holdings_table(
        holdings, detailed=request.detailed, fye_month=company.fye_month
    )
    if request.accounts:
        needles = [text.casefold() for text in request.accounts]
        rows = [row for row in rows if any(n in row.account.casefold() for n in needles)]
        investments = [i for i in investments if any(n in i.name.casefold() for n in needles)]
    notes = [n for n in (resolved.note, fallback_note(resolved.candidates, ref), shown) if n]
    notes.append("Book values are as carried on the company's own books, so basis does not apply.")
    if request.years > 1:
        notes.append("years does not apply to equity investments; this is the latest table.")
    return Table(
        periods, rows, notes, sources(holdings.filings, resolved.report), investments=investments
    )


async def _preliminary(
    state: AppState, company: Company, *, request: FinancialsRequest, progress: Progress
) -> Table:
    """Build the preliminary-earnings view from the latest KRX fair disclosure.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        request (FinancialsRequest): Request.
        progress (Progress): Progress callback.

    Returns:
        Table: Quarter columns, or an empty table with a note.
    """
    found = await latest_preliminary(state, company, progress=progress)
    if found is None:
        return Table(
            notes=[
                'No preliminary earnings disclosure was found among recent KRX fair disclosures; use view="summary" for the latest periodic report.'
            ]
        )
    table = preliminary_table(found, fye_month=company.fye_month, accounts=request.accounts)
    if request.period != "latest" or request.fiscal_year is not None or request.years > 1:
        table.notes.append(
            "period, fiscal_year, and years do not apply to the preliminary view, which shows the latest disclosure."
        )
    return table


_VIEWS: Final[Mapping[str, _View]] = MappingProxyType(
    {"ratios": _ratios, "equity_investments": _investments, "preliminary": _preliminary}
)


async def financials(
    state: AppState, company: str, request: FinancialsRequest, *, progress: Progress = no_progress
) -> FinancialsResult:
    """Build one company's financial statement view.

    Args:
        state (AppState): Server state.
        company (str): Name, stock code, or corp code.
        request (FinancialsRequest): View, basis, period, and output options.
        progress (Progress): Receives progress messages.

    Returns:
        FinancialsResult: Lines by period, derived metrics, and provenance.
    """
    resolved = await state.companies.resolve(company, progress=progress)
    build = _VIEWS.get(request.view, statements_view)
    table = await build(state, resolved, request=request, progress=progress)
    return FinancialsResult(
        company=resolved.ref,
        as_of=state.today(),
        view=request.view,
        basis_used=table.basis,
        unit=request.unit,
        currency=table.currency,
        periods=table.periods,
        rows=table.rows,
        derived=table.derived,
        investments=table.investments,
        source_filings=table.filings,
        notes=table.notes,
    )
