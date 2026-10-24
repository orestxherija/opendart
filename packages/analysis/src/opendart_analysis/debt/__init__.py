"""Debt securities from periodic reports: maturity ladders, issuance record, and maturities.

Six periodic-report services describe a company's debt securities: five balance tables by
remaining maturity (corporate bonds, short-term bonds, commercial paper, hybrid securities,
and contingent capital securities) and the record of issues in the period. Workflows take a
company, a resolved period (from ``opendart_analysis.reports.resolve_period``), the company's
names, and a ``FetchService``, following ``opendart_analysis.upstream``:

    resolved = await resolve_period(
        company, period="latest", fiscal_year=None, search_filings=search, today=today
    )
    profile = await debt_profile(
        company, resolved, names=names, fetch_service=fetch, today=today
    )

Amounts stay in won as filed. Modules: ``ladders`` (balance tables onto common buckets),
``issuance`` (the issuance record and maturities), ``profile``, and ``schedule``. Importing
this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.debt.issuance import (
    ISSUANCE_SERVICE,
    Issue,
    Maturity,
    Method,
    Redeemed,
    company_key,
    company_names,
    is_issue,
    issuance,
    issue,
    maturities,
    rating,
    redeemed,
)
from opendart_analysis.debt.ladders import (
    BONDS,
    LADDERS,
    Bucket,
    BucketAmount,
    DebtFigures,
    FiledColumn,
    Instrument,
    Ladder,
    LadderSpec,
    LadderTotals,
    MaturityBucket,
    Offering,
    build_ladder,
    derive,
    offering,
)
from opendart_analysis.debt.profile import (
    DEBT_SERVICES,
    DebtProfile,
    DebtTables,
    assemble,
    debt_profile,
    fetch_tables,
)
from opendart_analysis.debt.schedule import MaturitySchedule, maturity_schedule, prior_annual

__all__ = [
    "BONDS",
    "DEBT_SERVICES",
    "ISSUANCE_SERVICE",
    "LADDERS",
    "Bucket",
    "BucketAmount",
    "DebtFigures",
    "DebtProfile",
    "DebtTables",
    "FiledColumn",
    "Instrument",
    "Issue",
    "Ladder",
    "LadderSpec",
    "LadderTotals",
    "Maturity",
    "MaturityBucket",
    "MaturitySchedule",
    "Method",
    "Offering",
    "Redeemed",
    "assemble",
    "build_ladder",
    "company_key",
    "company_names",
    "debt_profile",
    "derive",
    "fetch_tables",
    "is_issue",
    "issuance",
    "issue",
    "maturities",
    "maturity_schedule",
    "offering",
    "prior_annual",
    "rating",
    "redeemed",
]
