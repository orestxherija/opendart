"""Profile a company: reference facts and its latest periodic report.

The latest final periodic report defines what "latest" means for periodic data: its period
comes first when ``opendart_analysis.reports.resolve_period`` resolves ``latest``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.extracts import FilingSource
from opendart_analysis.profile.facts import company_facts
from opendart_analysis.reports import latest_periodic_report

if TYPE_CHECKING:
    from datetime import date

    from opendart_analysis.profile.facts import CompanyFacts, CompanyOverview
    from opendart_analysis.reports import FiscalCompany, PeriodicReport
    from opendart_analysis.upstream import SearchFilings

NO_OVERVIEW: Final = "OpenDART has no company overview for this company."
"""Note for a company without an overview."""

NO_REPORT: Final = "No periodic report was filed in the last 15 months."
"""Note for a company without a recent periodic report."""


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    """A company's reference facts and latest periodic report.

    Attributes:
        facts (CompanyFacts): Reference facts from the overview.
        latest_report (PeriodicReport | None): Newest final periodic report from the last 15
            months, if any.
        sources (tuple[FilingSource, ...]): The latest report's filing, if any.
        notes (tuple[str, ...]): A missing overview, then a missing report.
    """

    facts: CompanyFacts
    latest_report: PeriodicReport | None
    sources: tuple[FilingSource, ...]
    notes: tuple[str, ...]


async def profile_company(
    company: FiscalCompany,
    overview: CompanyOverview | None,
    *,
    search_filings: SearchFilings,
    today: date,
) -> CompanyProfile:
    """Profile one company and find its latest periodic report, with one filing search.

    The overview is an input rather than a callable because resolving a company usually reads
    it already, for the fiscal year-end month.

    Args:
        company (FiscalCompany): Company; its fiscal year-end month dates report periods.
        overview (CompanyOverview | None): Its overview (``disclosures.company``), or None
            when the source has none.
        search_filings (SearchFilings): Filing search; one page of final periodic reports
            from the last 15 months, asked with ``high`` volatility.
        today (date): Today in KST.

    Returns:
        CompanyProfile: Facts, the latest periodic report, its filing, and notes.
    """
    report = await latest_periodic_report(company, search_filings=search_filings, today=today)
    notes = []
    if overview is None:
        notes.append(NO_OVERVIEW)
    if report is None:
        notes.append(NO_REPORT)
    return CompanyProfile(
        facts=company_facts(overview, company.fye_month),
        latest_report=report,
        sources=(FilingSource(report.filing_number, report.title),) if report else (),
        notes=tuple(notes),
    )
