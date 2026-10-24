"""Company profiles: reference facts from the overview and the latest periodic report.

The workflow takes a company (its corporation code and fiscal year-end month, which
``fiscal_year_end_month`` reads from the overview), its overview record, and a filing search,
following ``opendart_analysis.upstream``:

    profile = await profile_company(
        company, overview, search_filings=search, today=today_kst()
    )

Modules: ``facts`` (the overview normalized) and ``latest`` (the workflow). Importing this
package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.profile.facts import (
    CompanyFacts,
    CompanyOverview,
    company_facts,
    fiscal_year_end_month,
)
from opendart_analysis.profile.latest import (
    NO_OVERVIEW,
    NO_REPORT,
    CompanyProfile,
    profile_company,
)

__all__ = [
    "NO_OVERVIEW",
    "NO_REPORT",
    "CompanyFacts",
    "CompanyOverview",
    "CompanyProfile",
    "company_facts",
    "fiscal_year_end_month",
    "profile_company",
]
