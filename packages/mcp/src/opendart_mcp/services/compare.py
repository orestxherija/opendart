"""compare_companies: a peer table from OpenDART's multi-company services.

``fnltt_multi_acnt`` returns the major accounts of up to 100 companies in one call, both
bases per company, and ``fnltt_cmpny_indx`` one indicator category per call. Inputs resolve
concurrently, then ambiguous ones are settled one at a time, so a host that supports
elicitation asks about each in turn; unknown or ambiguous inputs and companies without data
go to ``missing`` instead of failing the call. The period is the newest candidate with data
for the most companies, so a few early filers do not empty the table; while its filing
deadline is recent, answers are cached briefly so that later filers appear the same day.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_mcp.core.errors import AmbiguousCompanyError, InvalidArgumentError
from opendart_mcp.core.interaction import choosing, current_chooser
from opendart_mcp.core.progress import no_progress
from opendart_mcp.domain.periods import FIRST_INDICATOR_YEAR, latest_candidates
from opendart_mcp.models.compare import CompareResult, MetricColumn, MissingCompany
from opendart_mcp.services import ratios
from opendart_mcp.services.fanout import gather
from opendart_mcp.services.peer_table import DECEMBER, Built, columns, notes, row as build_row
from opendart_mcp.services.periods import PROBE_ATTEMPTS
from opendart_mcp.services.tables import sources

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from opendart.models.financial_statements import FnlttMultiAcntResponseListItem
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.periods import PeriodRef
    from opendart_mcp.domain.types import Basis, Period, ResponseFormat, Unit
    from opendart_mcp.models.compare import CompareMetrics
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.ratios import IndicatorValue

    type Rows = Mapping[str, list[FnlttMultiAcntResponseListItem]]


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


@dataclass(frozen=True, slots=True)
class Probe:
    """The period chosen for the table and the data fetched for it.

    Attributes:
        ref (PeriodRef): Period.
        rows (Rows): Major-account rows by corp code (empty for ratios only).
        coverage (int): Companies with data.
        newest (PeriodRef): Newest candidate period, which may have had less data.
    """

    ref: PeriodRef
    rows: Rows
    coverage: int
    newest: PeriodRef


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


def _candidates(state: AppState, request: CompareRequest) -> tuple[PeriodRef, ...]:
    """List the periods to probe, newest first.

    Args:
        state (AppState): Server state.
        request (CompareRequest): Request.

    Returns:
        tuple[PeriodRef, ...]: Candidate periods.

    Raises:
        InvalidArgumentError: The period has not ended, predates the data, or (for ratios)
            predates OpenDART's indicators.
    """
    refs = latest_candidates(
        today=state.today(),
        period=request.period,
        fiscal_year=request.fiscal_year,
        fye_month=DECEMBER,
    )
    if request.metrics == "ratios":
        refs = tuple(ref for ref in refs if ref.fiscal_year >= FIRST_INDICATOR_YEAR)
        if not refs:
            message = f'OpenDART publishes financial indicators from fiscal {FIRST_INDICATOR_YEAR}; pass a later fiscal_year, or metrics="key_accounts".'
            raise InvalidArgumentError(message)
    if not refs:
        wanted = (
            f"{request.period} {request.fiscal_year}" if request.fiscal_year else request.period
        )
        message = f"No {wanted} period is available: it has not ended yet or predates 2015, when OpenDART's periodic data begins."
        raise InvalidArgumentError(message)
    return refs[:PROBE_ATTEMPTS]


def _owner(row: FnlttMultiAcntResponseListItem, by_stock: Mapping[str, str]) -> str | None:
    """Find the company a multi-company row belongs to.

    The live service adds ``corp_code`` to each row although the guide omits it; the stock
    code is the fallback.

    Args:
        row (FnlttMultiAcntResponseListItem): Upstream row.
        by_stock (Mapping[str, str]): Corp code by stock code.

    Returns:
        str | None: Corp code, or None when the row cannot be attributed.
    """
    code = (row.model_extra or {}).get("corp_code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return by_stock.get((row.stock_code or "").strip())


async def _accounts(state: AppState, companies: Sequence[Company], ref: PeriodRef) -> Rows:
    """Fetch the major accounts of every company for one period in one call.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Companies, at most 100.
        ref (PeriodRef): Period.

    Returns:
        Rows: Rows by corp code.
    """
    gateway = state.require_gateway()
    response = await gateway.call(
        ratios.peer_ttl(state, companies, ref),
        gateway.sdk.financial_statements.fnltt_multi_acnt,
        corporation_codes=[company.corp_code for company in companies],
        fiscal_year=str(ref.fiscal_year),
        report_period=ref.report_code,
    )
    by_stock = {c.ref.stock_code: c.corp_code for c in companies if c.ref.stock_code}
    grouped: dict[str, list[FnlttMultiAcntResponseListItem]] = {}
    for row in (response.list or []) if response is not None else []:
        owner = _owner(row, by_stock)
        if owner is not None:
            grouped.setdefault(owner, []).append(row)
    return grouped


async def _probe(
    state: AppState, companies: Sequence[Company], request: CompareRequest, *, progress: Progress
) -> Probe | None:
    """Choose the newest candidate period with data for the most companies.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Resolved companies.
        request (CompareRequest): Request.
        progress (Progress): Progress callback.

    Returns:
        Probe | None: Chosen period and its data, or None when no candidate has data.
    """
    best: Probe | None = None
    candidates = _candidates(state, request)
    for ref in candidates:
        await progress(f"Fetching {ref.label} for {len(companies)} companies")
        if request.metrics == "ratios":
            values = await ratios.peer_indicators(state, companies, ref, categories=("M210000",))
            covered = len({v.corp_code for v in values if v.value is not None})
            probe = Probe(ref, {}, covered, candidates[0])
        else:
            rows = await _accounts(state, companies, ref)
            probe = Probe(ref, rows, len(rows), candidates[0])
        if best is None or probe.coverage > best.coverage:
            best = probe
        if probe.coverage == len(companies):
            break
    return best if best is not None and best.coverage else None


async def _indicators(
    state: AppState, companies: Sequence[Company], probe: Probe, *, request: CompareRequest
) -> tuple[list[IndicatorValue], list[str]]:
    """Fetch every indicator category when the metric set includes ratios.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Resolved companies.
        probe (Probe): Chosen period.
        request (CompareRequest): Request.

    Returns:
        tuple[list[IndicatorValue], list[str]]: Indicator values and notes.
    """
    if request.metrics == "key_accounts":
        return [], []
    if probe.ref.fiscal_year < FIRST_INDICATOR_YEAR:
        note = f"OpenDART publishes indicators from fiscal {FIRST_INDICATOR_YEAR}; only accounts are shown."
        return [], [note]
    return await ratios.peer_indicators(state, companies, probe.ref), []


async def _table(
    state: AppState,
    companies: Sequence[Company],
    probe: Probe,
    *,
    request: CompareRequest,
    progress: Progress,
) -> Built:
    """Fetch indicators if needed and lay out the peer table.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Resolved companies.
        probe (Probe): Chosen period and major-account rows.
        request (CompareRequest): Request.
        progress (Progress): Progress callback.

    Returns:
        Built: Columns, rows, missing companies, notes, and filings.
    """
    if request.metrics != "key_accounts":
        await progress(f"Fetching {probe.ref.label} indicators")
    indicators, caveats = await _indicators(state, companies, probe, request=request)
    by_company: dict[str, dict[str, float | None]] = {}
    for value in indicators:
        by_company.setdefault(value.corp_code or "", {})[value.code] = value.value
    chosen = columns(request, indicators)
    built = Built(chosen, [], [], caveats, [])
    for company in companies:
        values = by_company.get(company.corp_code, {})
        row = build_row(company, probe, values, columns=chosen, request=request)
        if isinstance(row, str):
            built.missing.append(MissingCompany(company=company.ref.name, reason=row))
            continue
        built.rows.append(row)
        filed = [r.filing_number for r in probe.rows.get(company.corp_code, []) if r.filing_number]
        built.filings = sources([*(f.filing_number for f in built.filings), *filed[:1]], None)
    built.notes += notes(companies, built, probe, request=request)
    return built


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
    probe = await _probe(state, resolved, request, progress=progress) if resolved else None
    if probe is None:
        reason = "No data in OpenDART for the requested period (not filed yet, or not covered)."
        missing += [MissingCompany(company=company.ref.name, reason=reason) for company in resolved]
        notes.append(
            "No company has data for the requested period; see missing."
            if resolved
            else "No company could be resolved; see missing."
        )
        built = Built([], [], [], [], [])
    else:
        built = await _table(state, resolved, probe, request=request, progress=progress)
    return CompareResult(
        as_of=state.today(),
        company_count=len(built.rows),
        fiscal_year=probe.ref.fiscal_year if probe else None,
        period=probe.ref.period if probe else None,
        basis=request.basis,
        unit=request.unit,
        columns=[MetricColumn(key=c.key, label=c.label, unit=c.unit) for c in built.columns],
        rows=built.rows,
        missing=[*missing, *built.missing],
        notes=[*notes, *built.notes],
        source_filings=built.filings,
    )
