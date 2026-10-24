"""Company search and company profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import anyio

from opendart_analysis.domain.normalize import clean_text, market_from_corp_cls, parse_date
from opendart_analysis.domain.resolver import resolve
from opendart_mcp.core.progress import no_progress
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.company import (
    CompanyMatch,
    CompanyProfile,
    CompanyProfileResult,
    FindCompanyResult,
    PeriodicReportRef,
)
from opendart_mcp.services.periods import latest_periodic_report

if TYPE_CHECKING:
    from opendart.models import CompanyResponse
    from opendart_analysis.domain.directory import Match
    from opendart_analysis.domain.types import Market, MarketFilter
    from opendart_mcp.core.interaction import Chooser
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.periods import PeriodicReport

_LISTED_MARKETS: Final[dict[str, Market]] = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KONEX": "KONEX"}
_DOMINANT: Final = frozenset({"code", "exact", "dominant"})
# Market filters need a profile per candidate; look at a few more than requested.
_MARKET_OVERFETCH: Final = 3


def _match(match: Match, market: Market | None = None) -> CompanyMatch:
    """Describe a directory match.

    Args:
        match (Match): Ranked directory result.
        market (Market | None): Listing market, when known.

    Returns:
        CompanyMatch: Output entry.
    """
    record = match.record
    return CompanyMatch(
        corp_code=record.corp_code,
        name=record.english_name or record.name,
        korean_name=record.name,
        stock_code=record.stock_code,
        market=market,
        listed=record.listed,
        last_modified=record.modified,
        match=match.tier,
    )


async def _with_markets(
    state: AppState, matches: tuple[Match, ...], *, market: Market, limit: int
) -> list[CompanyMatch]:
    """Keep matches listed on one market, fetching profiles concurrently.

    Args:
        state (AppState): Server state.
        matches (tuple[Match, ...]): Listed candidates, best first.
        market (Market): Required market.
        limit (int): Maximum results.

    Returns:
        list[CompanyMatch]: Matches on the market, in rank order.
    """
    markets: dict[str, Market | None] = {}

    async def lookup(code: str) -> None:
        """Resolve a company's listing market from its profile.

        Args:
            code (str): Corporation code to look up.

        Returns:
            None: Stores the resolved market in the enclosing lookup map.
        """
        profile = await state.companies.profile(code)
        markets[code] = market_from_corp_cls(profile.corporation_type if profile else None)

    async with anyio.create_task_group() as tasks:
        for match in matches:
            tasks.start_soon(lookup, match.record.corp_code)
    kept = [m for m in matches if markets.get(m.record.corp_code) == market]
    return [_match(m, market) for m in kept[:limit]]


async def find_companies(
    state: AppState,
    query: str,
    *,
    market: MarketFilter = "all",
    limit: int = 10,
    progress: Progress = no_progress,
) -> FindCompanyResult:
    """Search the company directory.

    Args:
        state (AppState): Server state.
        query (str): Name, stock code, or corp code.
        market (MarketFilter): Restrict to one market, or to unlisted companies.
        limit (int): Maximum matches.
        progress (Progress): Reports progress while the directory loads.

    Returns:
        FindCompanyResult: Ranked matches and the dominant match, if any.
    """
    directory = await state.directory.wait(state.settings.directory.wait, progress)
    listed = None if market == "all" else market != "unlisted"
    listed_market = _LISTED_MARKETS.get(market)
    if listed_market is not None:
        candidates = directory.search(query, listed=True, limit=limit * _MARKET_OVERFETCH)
        matches = await _with_markets(state, candidates, market=listed_market, limit=limit)
    else:
        matches = [_match(m) for m in directory.search(query, listed=listed, limit=limit)]
    resolution = resolve(directory, query)
    best = None
    if resolution.record is not None and resolution.reason in _DOMINANT:
        best = next((m for m in matches if m.corp_code == resolution.record.corp_code), None)
    notes = (
        []
        if matches
        else [
            f"No company matches '{query}'. Try the Korean name, a shorter name, or a stock code."
        ]
    )
    if listed_market is not None:
        notes.append(
            "Markets come from company profiles; listed companies are checked in rank order."
        )
    return FindCompanyResult(
        query=query, matches=matches, best_match=best, as_of=state.today(), notes=notes
    )


def _profile(profile: CompanyResponse | None, fye_month: int) -> CompanyProfile:
    """Normalize the company overview.

    Args:
        profile (CompanyResponse | None): Upstream overview.
        fye_month (int): Fiscal year-end month.

    Returns:
        CompanyProfile: Reference facts.
    """
    if profile is None:
        return CompanyProfile(fiscal_year_end_month=fye_month)
    return CompanyProfile(
        stock_name=clean_text(profile.stock_name),
        ceo=clean_text(profile.ceo_nm),
        industry_code=clean_text(profile.induty_code),
        fiscal_year_end_month=fye_month,
        established=parse_date(profile.est_dt),
        address=clean_text(profile.adres),
        website=clean_text(profile.hm_url),
        ir_url=clean_text(profile.ir_url),
        phone=clean_text(profile.phn_no),
        fax=clean_text(profile.fax_no),
        corporate_registration_number=clean_text(profile.jurir_no),
        business_registration_number=clean_text(profile.bizr_no),
    )


def _report_ref(report: PeriodicReport) -> PeriodicReportRef:
    """Describe the latest periodic report.

    Args:
        report (PeriodicReport): Report found in the filing index.

    Returns:
        PeriodicReportRef: Output entry.
    """
    return PeriodicReportRef(
        kind=report.parsed.kind,
        fiscal_year=report.ref.fiscal_year,
        period=report.ref.period,
        period_end=report.ref.end_date,
        filed=report.filed,
        filing_number=report.filing_number,
        title=report.title,
    )


async def company_profile(
    state: AppState,
    company: str,
    *,
    progress: Progress = no_progress,
    choose: Chooser | None = None,
) -> CompanyProfileResult:
    """Profile one company and find its latest periodic report.

    Args:
        state (AppState): Server state.
        company (str): Name, stock code, or corp code.
        progress (Progress): Reports progress while the directory loads.
        choose (Chooser | None): Asks the user to pick among ambiguous matches.

    Returns:
        CompanyProfileResult: Identity, reference facts, and the latest periodic report.
    """
    resolved = await state.companies.resolve(company, progress=progress, choose=choose)
    report = await latest_periodic_report(state, resolved)
    notes = []
    if resolved.profile is None:
        notes.append("OpenDART has no company overview for this company.")
    if report is None:
        notes.append("No periodic report was filed in the last 15 months.")
    return CompanyProfileResult(
        company=resolved.ref,
        profile=_profile(resolved.profile, resolved.fye_month),
        latest_periodic_report=_report_ref(report) if report else None,
        source_filings=[SourceFiling.of(report.filing_number, report.title)] if report else [],
        notes=notes,
        as_of=state.today(),
    )
