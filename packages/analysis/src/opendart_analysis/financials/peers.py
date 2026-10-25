"""Peer comparison from OpenDART's multi-company services.

The multi-company major accounts (``fnltt_multi_acnt``) return up to 100 companies in one
answer, both bases per company, and the multi-company indicators (``fnltt_cmpny_indx``) one
category per request. The period is the newest candidate with data for the most companies,
so a few early filers do not empty the comparison. Account values are year to date for
quarterly income lines; derived metrics are computed from them, and indicators are OpenDART's
published values.

Acquisition is bounded: at most ``PROBE_ATTEMPTS`` candidate periods are probed with one
request each, then the four indicator categories are read once when ratios are wanted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from opendart_analysis.domain.periods import DECEMBER, FIRST_INDICATOR_YEAR, latest_candidates
from opendart_analysis.errors import NotConfiguredError
from opendart_analysis.financials import derived
from opendart_analysis.financials.access import PeerQuery, check_peer_count
from opendart_analysis.financials.indicators import (
    IndicatorsUnavailableError,
    peer_indicators,
    peer_volatility,
)
from opendart_analysis.financials.specs import SCOPES
from opendart_analysis.financials.statements import build_report, shift, summary_item
from opendart_analysis.reports import PROBE_ATTEMPTS, PeriodUnavailableError
from opendart_analysis.upstream import no_progress

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from datetime import date

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Basis, Period
    from opendart_analysis.financials.access import FetchPeerAccounts, PeerAccountRecord
    from opendart_analysis.financials.indicators import FetchPeerIndicators, IndicatorValue
    from opendart_analysis.financials.statements import Number, StatementBasis
    from opendart_analysis.upstream import Progress

    type Rows = Mapping[str, list[PeerAccountRecord]]
    type Measure = Callable[[PeriodRef], Awaitable[_Probe]]

type PeerMetrics = Literal["key_accounts", "ratios", "both"]
"""Values to compare: major accounts with derived metrics, published indicators, or both."""

"""Fiscal year-end month that labels the compared period."""


class PeerCompany(Protocol):
    """The company facts a peer comparison reads."""

    @property
    def corp_code(self) -> str:
        """8-digit DART corporation code."""
        ...

    @property
    def fye_month(self) -> int:
        """Fiscal year-end month, 1 to 12."""
        ...

    @property
    def stock_code(self) -> str | None:
        """6-character stock code, which attributes rows that lack a corporation code."""
        ...


@dataclass(frozen=True, slots=True)
class Peer:
    """A company to compare.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        fye_month (int): Fiscal year-end month, 1 to 12.
        stock_code (str | None): 6-character stock code, if listed.
    """

    corp_code: str
    fye_month: int = DECEMBER
    stock_code: str | None = None


@dataclass(frozen=True, slots=True)
class PeerRequest:
    """What to compare and for which period.

    Attributes:
        metrics (PeerMetrics): Values to compare.
        period (Period): Requested period; periods are labeled by December year ends.
        fiscal_year (int | None): Requested fiscal year; None means the newest with data.
        basis (Basis): ``auto`` prefers consolidated statements per company.
    """

    metrics: PeerMetrics = "key_accounts"
    period: Period = "FY"
    fiscal_year: int | None = None
    basis: Basis = "consolidated"


@dataclass(frozen=True, slots=True)
class PeerValues:
    """One company's values for the compared period.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        accounts (Mapping[str, Number | None] | None): Major-account values by metric key
            (such as ``revenue``) and derived metrics in percent (such as ``net_margin``);
            None when accounts were not wanted or none are filed on the requested basis.
        basis (StatementBasis | None): Statements the account values come from.
        indicators (Mapping[str, float | None]): Published indicators by code, in percent.
        filed (bool): Whether the company filed major accounts on any basis.
        filings (tuple[str, ...]): Filing numbers of the company's major-account rows.
    """

    corp_code: str
    accounts: Mapping[str, Number | None] | None
    basis: StatementBasis | None
    indicators: Mapping[str, float | None] = field(default_factory=dict)
    filed: bool = False
    filings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PeerComparison:
    """Values of several companies for one period.

    Attributes:
        ref (PeriodRef): Compared period: the newest candidate with data for the most
            companies.
        newest (PeriodRef): Newest candidate period, which may have had less data.
        coverage (int): Companies with data for ``ref``.
        peers (tuple[PeerValues, ...]): One entry per company, in input order.
        indicators (tuple[IndicatorValue, ...]): Every indicator value read, in upstream order.
        notes (tuple[str, ...]): Caveats, such as indicators predating fiscal 2022.
    """

    ref: PeriodRef
    newest: PeriodRef
    coverage: int
    peers: tuple[PeerValues, ...]
    indicators: tuple[IndicatorValue, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Probe:
    """A candidate period and the data fetched for it."""

    ref: PeriodRef
    rows: Rows
    coverage: int


def candidates(request: PeerRequest, *, today: date) -> tuple[PeriodRef, ...]:
    """List the periods to probe, newest first.

    Args:
        request (PeerRequest): Request.
        today (date): Today in KST.

    Returns:
        tuple[PeriodRef, ...]: At most ``PROBE_ATTEMPTS`` candidate periods.

    Raises:
        IndicatorsUnavailableError: Only ratios are wanted and every candidate predates
            OpenDART's indicators.
        PeriodUnavailableError: The period has not ended yet or predates 2015.
    """
    refs = latest_candidates(
        today=today, period=request.period, fiscal_year=request.fiscal_year, fye_month=DECEMBER
    )
    if request.metrics == "ratios":
        refs = tuple(ref for ref in refs if ref.fiscal_year >= FIRST_INDICATOR_YEAR)
        if not refs:
            raise IndicatorsUnavailableError(request.fiscal_year)
    if not refs:
        raise PeriodUnavailableError(request.period, request.fiscal_year)
    return refs[:PROBE_ATTEMPTS]


def owner(row: PeerAccountRecord, by_stock: Mapping[str, str]) -> str | None:
    """Find the company a multi-company row belongs to.

    The live service adds ``corp_code`` to each row although its guide omits it; the stock
    code is the fallback.

    Args:
        row (PeerAccountRecord): Upstream row.
        by_stock (Mapping[str, str]): Corp code by stock code.

    Returns:
        str | None: Corp code, or None when the row cannot be attributed.
    """
    code = getattr(row, "corp_code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    return by_stock.get((row.stock_code or "").strip())


def _account_values(rows: Sequence[PeerAccountRecord], ref: PeriodRef) -> dict[str, Number | None]:
    """Read key accounts (year to date for quarterly income) and derived metrics.

    Args:
        rows (Sequence[PeerAccountRecord]): One company's rows on one basis.
        ref (PeriodRef): Period.

    Returns:
        dict[str, Number | None]: Values by metric key and derived key.
    """
    report = build_report(
        [summary_item(row) for row in rows], ref, rank=lambda _, position: position
    )
    pairs = derived.metric_values(report.lines, ref, shift(ref, 1))
    return {**{key: pair[0] for key, pair in pairs.items()}, **derived.compute(pairs)}


def _values(
    corp_code: str, probe: _Probe, *, indicators: Mapping[str, float | None], basis: Basis
) -> PeerValues:
    """Collect one company's values, choosing its rows for the requested basis.

    Args:
        corp_code (str): Company.
        probe (_Probe): Chosen period and major-account rows.
        indicators (Mapping[str, float | None]): The company's indicators by code.
        basis (Basis): Requested basis; auto prefers consolidated.

    Returns:
        PeerValues: The company's values.
    """
    rows = probe.rows.get(corp_code, [])
    filings = tuple(row.filing_number for row in rows if row.filing_number)
    for scope, used in SCOPES[basis] if rows else ():
        chosen = [row for row in rows if (row.statement_scope or "").upper() == scope]
        if chosen:
            values = _account_values(chosen, probe.ref)
            return PeerValues(corp_code, values, used, indicators, filed=True, filings=filings)
    return PeerValues(corp_code, None, None, indicators, filed=bool(rows), filings=filings)


def _require[T](dependency: T | None, name: str) -> T:
    """Return a data-access callable the request needs.

    Args:
        dependency (T | None): The callable, if supplied.
        name (str): Parameter name of the callable.

    Returns:
        T: The callable.

    Raises:
        NotConfiguredError: The callable was not supplied.
    """
    if dependency is None:
        message = f"This comparison needs {name}, which was not supplied."
        raise NotConfiguredError(message, dependency=name)
    return dependency


async def compare_peers(
    companies: Sequence[PeerCompany],
    *,
    request: PeerRequest,
    fetch_peer_accounts: FetchPeerAccounts | None = None,
    fetch_peer_indicators: FetchPeerIndicators | None = None,
    today: date,
    progress: Progress | None = None,
) -> PeerComparison | None:
    """Compare several companies for the newest period with data for the most of them.

    Args:
        companies (Sequence[PeerCompany]): Distinct companies, 1 to 100.
        request (PeerRequest): Values, period, and basis.
        fetch_peer_accounts (FetchPeerAccounts | None): Needed unless only ratios are wanted.
        fetch_peer_indicators (FetchPeerIndicators | None): Needed when ratios are wanted.
        today (date): Today in KST, which sets the candidates and their volatility.
        progress (Progress | None): Receives one message per request.

    Returns:
        PeerComparison | None: Values per company, or None when no candidate period has data
            for any company.

    Raises:
        ValueError: ``companies`` is empty or longer than 100.
        NotConfiguredError: A data-access callable the request needs was not supplied.
        IndicatorsUnavailableError: Only ratios are wanted for a period before fiscal 2022.
        PeriodUnavailableError: The period has not ended yet or predates 2015.
    """
    check_peer_count(len(companies))
    report = progress or no_progress
    measure = _measure(
        companies, request, accounts=fetch_peer_accounts, ratios=fetch_peer_indicators, today=today
    )
    ratios = (
        None
        if request.metrics == "key_accounts"
        else _require(fetch_peer_indicators, "fetch_peer_indicators")
    )
    refs = candidates(request, today=today)
    probe = await _probe(refs, measure, count=len(companies), progress=report)
    if probe is None:
        return None
    values, notes = await _indicators(
        companies, probe.ref, fetch=ratios, today=today, progress=report
    )
    by_company: dict[str, dict[str, float | None]] = {}
    for value in values:
        by_company.setdefault(value.corp_code or "", {})[value.code] = value.value
    peers = tuple(
        _values(c.corp_code, probe, indicators=by_company.get(c.corp_code, {}), basis=request.basis)
        for c in companies
    )
    return PeerComparison(probe.ref, refs[0], probe.coverage, peers, tuple(values), notes)


async def _rows(
    companies: Sequence[PeerCompany], ref: PeriodRef, *, fetch: FetchPeerAccounts, today: date
) -> Rows:
    """Fetch the major accounts of every company for one period in one request.

    Args:
        companies (Sequence[PeerCompany]): Companies.
        ref (PeriodRef): Period.
        fetch (FetchPeerAccounts): Multi-company major accounts; asked with
            ``peer_volatility``.
        today (date): Today in KST.

    Returns:
        Rows: Rows by corp code; rows that cannot be attributed are dropped.
    """
    query = PeerQuery(tuple(c.corp_code for c in companies), ref.fiscal_year, ref.report_code)
    records = await fetch(query, volatility=peer_volatility(companies, ref, today=today))
    by_stock = {c.stock_code: c.corp_code for c in companies if c.stock_code}
    grouped: dict[str, list[PeerAccountRecord]] = {}
    for row in records or ():
        code = owner(row, by_stock)
        if code is not None:
            grouped.setdefault(code, []).append(row)
    return grouped


def _measure(
    companies: Sequence[PeerCompany],
    request: PeerRequest,
    *,
    accounts: FetchPeerAccounts | None,
    ratios: FetchPeerIndicators | None,
    today: date,
) -> Measure:
    """Choose how a candidate period's coverage is measured.

    Args:
        companies (Sequence[PeerCompany]): Companies.
        request (PeerRequest): Request; ratios alone are probed with profitability indicators.
        accounts (FetchPeerAccounts | None): Major accounts, needed unless only ratios are
            wanted.
        ratios (FetchPeerIndicators | None): Indicators, needed when only ratios are wanted.
        today (date): Today in KST.

    Returns:
        Measure: Fetches one candidate period and counts the companies with data.

    Raises:
        NotConfiguredError: The data access the request needs was not supplied.
    """
    if request.metrics == "ratios":
        fetch_ratios = _require(ratios, "fetch_peer_indicators")

        async def profitability(ref: PeriodRef) -> _Probe:
            """Count the companies with any published profitability indicator.

            Args:
                ref (PeriodRef): Candidate period.

            Returns:
                _Probe: The period without rows, and its coverage.
            """
            values = await peer_indicators(
                companies,
                ref,
                categories=("M210000",),
                fetch_peer_indicators=fetch_ratios,
                today=today,
            )
            return _Probe(ref, {}, len({v.corp_code for v in values if v.value is not None}))

        return profitability
    fetch_accounts = _require(accounts, "fetch_peer_accounts")

    async def filed(ref: PeriodRef) -> _Probe:
        """Count the companies with major-account rows.

        Args:
            ref (PeriodRef): Candidate period.

        Returns:
            _Probe: The period, its rows, and its coverage.
        """
        rows = await _rows(companies, ref, fetch=fetch_accounts, today=today)
        return _Probe(ref, rows, len(rows))

    return filed


async def _probe(
    refs: Sequence[PeriodRef], measure: Measure, *, count: int, progress: Progress
) -> _Probe | None:
    """Choose the newest candidate period with data for the most companies.

    Args:
        refs (Sequence[PeriodRef]): Candidate periods, newest first.
        measure (Measure): Fetches one candidate and counts the companies with data.
        count (int): Companies compared; a candidate covering all of them ends the search.
        progress (Progress): Receives one message per candidate.

    Returns:
        _Probe | None: Chosen period and its rows, or None when no candidate has data.
    """
    best: _Probe | None = None
    for ref in refs:
        await progress(f"Fetching {ref.label} for {count} companies")
        probe = await measure(ref)
        if best is None or probe.coverage > best.coverage:
            best = probe
        if probe.coverage == count:
            break
    return best if best is not None and best.coverage else None


async def _indicators(
    companies: Sequence[PeerCompany],
    ref: PeriodRef,
    *,
    fetch: FetchPeerIndicators | None,
    today: date,
    progress: Progress,
) -> tuple[list[IndicatorValue], tuple[str, ...]]:
    """Read every indicator category for the compared period when ratios are wanted.

    Args:
        companies (Sequence[PeerCompany]): Companies.
        ref (PeriodRef): Compared period.
        fetch (FetchPeerIndicators | None): Indicators; None when ratios are not wanted.
        today (date): Today in KST.
        progress (Progress): Receives one message before the indicators are read.

    Returns:
        tuple[list[IndicatorValue], tuple[str, ...]]: Values and caveats.
    """
    if fetch is None:
        return [], ()
    await progress(f"Fetching {ref.label} indicators")
    if ref.fiscal_year < FIRST_INDICATOR_YEAR:
        note = f"OpenDART publishes indicators from fiscal {FIRST_INDICATOR_YEAR}; only accounts are shown."
        return [], (note,)
    return await peer_indicators(companies, ref, fetch_peer_indicators=fetch, today=today), ()
