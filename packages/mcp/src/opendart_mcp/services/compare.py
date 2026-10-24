"""compare_companies: a peer table from OpenDART's multi-company services.

Inputs resolve concurrently, then ambiguous ones are settled one at a time, so a host that
supports elicitation asks about each in turn; unknown or ambiguous inputs and companies
without data go to ``missing`` instead of failing the call.
``opendart_analysis.financials.compare_peers`` then picks the newest candidate period with
data for the most companies, so a few early filers do not empty the table, and reads each
company's values; while the period's filing deadline is recent, answers are cached briefly
so that later filers appear the same day. ``peer_table`` lays out the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_analysis.domain.periods import FIRST_INDICATOR_YEAR
from opendart_analysis.errors import AnalysisError
from opendart_analysis.financials import (
    IndicatorsUnavailableError,
    Peer,
    PeerRequest,
    compare_peers,
)
from opendart_mcp.core.errors import AmbiguousCompanyError, InvalidArgumentError, from_analysis
from opendart_mcp.core.interaction import choosing, current_chooser
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream_financials import peer_accounts_fetch, peer_indicators_fetch
from opendart_mcp.models.compare import CompareResult, MetricColumn, MissingCompany
from opendart_mcp.services.fanout import gather
from opendart_mcp.services.peer_table import Built, build

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from opendart_analysis.domain.types import Basis, Period, Unit
    from opendart_analysis.financials import PeerComparison
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.models.compare import CompareMetrics
    from opendart_mcp.services.companies import Company


@dataclass(frozen=True, slots=True)
class CompareRequest:
    """What compare_companies was asked for.

    Attributes:
        metrics (CompareMetrics): Metric set.
        fiscal_year (int | None): Requested fiscal year.
        period (Period): Requested period.
        basis (Basis): Requested basis.
        unit (Unit): Display unit of the text table.
        response_format (ResponseFormat): Concise or detailed.
    """

    metrics: CompareMetrics = "key_accounts"
    fiscal_year: int | None = None
    period: Period = "FY"
    basis: Basis = "consolidated"
    unit: Unit = "million_krw"
    response_format: ResponseFormat = "concise"


def _first_pass(
    state: AppState, text: str, *, progress: Progress
) -> Callable[[], Awaitable[Company | InvalidArgumentError]]:
    """Bind the resolution of one input, returning rather than raising a bad input.

    Args:
        state (AppState): Server state.
        text (str): Company name or code.
        progress (Progress): Progress callback.

    Returns:
        Callable[[], Awaitable[Company | InvalidArgumentError]]: Call to await.
    """

    async def call() -> Company | InvalidArgumentError:
        """Resolve the input while returning invalid-input errors as values.

        Returns:
            Company | InvalidArgumentError: The resolved company or its resolution error.
        """
        try:
            return await state.companies.resolve(text, progress=progress)
        except InvalidArgumentError as error:
            return error

    return call


async def _settle(
    state: AppState, text: str, outcome: Company | InvalidArgumentError, *, progress: Progress
) -> Company | MissingCompany:
    """Finish one input after the concurrent first pass, asking about an ambiguous one.

    Args:
        state (AppState): Server state.
        text (str): Company name or code as given.
        outcome (Company | InvalidArgumentError): First-pass result.
        progress (Progress): Progress callback.

    Returns:
        Company | MissingCompany: The company, or why the input was left out.
    """
    if isinstance(outcome, AmbiguousCompanyError) and current_chooser() is not None:
        try:
            outcome = await state.companies.resolve(text, progress=progress)
        except InvalidArgumentError as error:
            outcome = error
    if isinstance(outcome, InvalidArgumentError):
        return MissingCompany(company=text, reason=str(outcome))
    return outcome


async def _resolve_all(
    state: AppState, inputs: Sequence[str], *, progress: Progress
) -> tuple[list[Company], list[MissingCompany], list[str]]:
    """Resolve every input, keeping unknown and ambiguous ones aside.

    Inputs resolve concurrently without asking the user; ambiguous ones are then settled one
    at a time, so a host that supports elicitation shows one question at a time.

    Args:
        state (AppState): Server state.
        inputs (Sequence[str]): Company names or codes.
        progress (Progress): Progress callback.

    Returns:
        tuple[list[Company], list[MissingCompany], list[str]]: Distinct companies in input
            order, inputs that could not be resolved, and notes about duplicates.
    """
    with choosing(None):
        first = await gather([_first_pass(state, text, progress=progress) for text in inputs])
    companies: dict[str, Company] = {}
    missing: list[MissingCompany] = []
    for text, outcome in zip(inputs, first, strict=True):
        found = await _settle(state, text, outcome, progress=progress)
        if isinstance(found, MissingCompany):
            missing.append(found)
        else:
            companies.setdefault(found.corp_code, found)
    duplicates = len(inputs) - len(missing) - len(companies)
    notes = (
        [f"{duplicates} duplicate input(s) resolved to the same company and were merged."]
        if duplicates
        else []
    )
    await progress(f"Resolved {len(companies)}/{len(inputs)} companies")
    return list(companies.values()), missing, notes


async def _compare(
    state: AppState, companies: Sequence[Company], request: CompareRequest, *, progress: Progress
) -> PeerComparison | None:
    """Compare resolved companies through the gateway.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Distinct resolved companies.
        request (CompareRequest): Request.
        progress (Progress): Progress callback.

    Returns:
        PeerComparison | None: Values per company, or None when no candidate has data.

    Raises:
        InvalidArgumentError: The period has not ended, predates the data, or (for ratios)
            predates OpenDART's indicators.
    """
    peers = [Peer(c.corp_code, c.fye_month, c.ref.stock_code) for c in companies]
    wanted = PeerRequest(request.metrics, request.period, request.fiscal_year, request.basis)
    try:
        return await compare_peers(
            peers,
            request=wanted,
            fetch_peer_accounts=peer_accounts_fetch(state.require_gateway),
            fetch_peer_indicators=peer_indicators_fetch(state.require_gateway),
            today=state.today(),
            progress=progress,
        )
    except IndicatorsUnavailableError as error:
        message = f'OpenDART publishes financial indicators from fiscal {FIRST_INDICATOR_YEAR}; pass a later fiscal_year, or metrics="key_accounts".'
        raise InvalidArgumentError(message) from error
    except AnalysisError as error:
        raise from_analysis(error) from error


async def compare_companies(
    state: AppState,
    companies: Sequence[str],
    request: CompareRequest,
    *,
    progress: Progress = no_progress,
) -> CompareResult:
    """Build a peer table for several companies.

    Args:
        state (AppState): Server state.
        companies (Sequence[str]): Names, stock codes, or corp codes.
        request (CompareRequest): Metric set, period, basis, and output options.
        progress (Progress): Receives progress messages.

    Returns:
        CompareResult: Columns, one row per company with data, and the companies left out.
    """
    state.require_gateway()
    resolved, missing, notes = await _resolve_all(state, companies, progress=progress)
    found = await _compare(state, resolved, request, progress=progress) if resolved else None
    if found is None:
        reason = "No data in OpenDART for the requested period (not filed yet, or not covered)."
        missing += [MissingCompany(company=company.ref.name, reason=reason) for company in resolved]
        notes.append(
            "No company has data for the requested period; see missing."
            if resolved
            else "No company could be resolved; see missing."
        )
        built = Built([], [], [], [], [])
    else:
        built = build(resolved, found, request=request)
    return CompareResult(
        as_of=state.today(),
        company_count=len(built.rows),
        fiscal_year=found.ref.fiscal_year if found else None,
        period=found.ref.period if found else None,
        basis=request.basis,
        unit=request.unit,
        columns=[MetricColumn(key=c.key, label=c.label, unit=c.unit) for c in built.columns],
        rows=built.rows,
        missing=[*missing, *built.missing],
        notes=[*notes, *built.notes],
        source_filings=built.filings,
    )
