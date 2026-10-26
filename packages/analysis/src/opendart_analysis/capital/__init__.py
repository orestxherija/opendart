"""Capital structure: share counts, treasury stock, capital changes, and use of proceeds.

Every section comes from one periodic report. ``capital_structure`` takes the company, a
period resolved by ``opendart_analysis.reports.resolve_period``, and the tables it needs as
keyword-only callables, following ``opendart_analysis.upstream``:

    resolved = await resolve_period(
        company, period="latest", fiscal_year=None, search_filings=search, today=today
    )
    structure = await capital_structure(
        company, resolved, sections=("shares",), fetch_share_counts=fetch, today=today
    )

Share counts are integers and amounts are won as filed; share classes read ``common``,
``preferred``, ``total`` (all classes), or the class as filed. Modules: ``shares`` (the
share-count table), ``treasury``, ``changes`` (issuances, reductions, and use of proceeds),
and ``structure`` (the workflow). Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.capital.changes import (
    CapitalChange,
    CapitalChangeRecord,
    FetchCapitalChanges,
    FetchPrivateProceeds,
    FetchPublicProceeds,
    Offering,
    PrivateProceedsRecord,
    ProceedsRecord,
    ProceedsUse,
    PublicProceedsRecord,
    capital_changes,
    change_category,
    proceeds_uses,
)
from opendart_analysis.capital.shares import (
    COMMON,
    PREFERRED,
    TOTAL,
    FetchShareCounts,
    ShareClassCounts,
    ShareCountRecord,
    ShareCounts,
    is_note,
    latest_share_counts,
    parse_share_counts,
    period_share_counts,
    share_class,
)
from opendart_analysis.capital.structure import (
    SECTIONS,
    CapitalStructure,
    Section,
    capital_structure,
)
from opendart_analysis.capital.treasury import (
    FetchTreasuryStock,
    TreasuryMovement,
    TreasuryRecord,
    treasury_methods,
    treasury_totals,
)

__all__ = [
    "COMMON",
    "PREFERRED",
    "SECTIONS",
    "TOTAL",
    "CapitalChange",
    "CapitalChangeRecord",
    "CapitalStructure",
    "FetchCapitalChanges",
    "FetchPrivateProceeds",
    "FetchPublicProceeds",
    "FetchShareCounts",
    "FetchTreasuryStock",
    "Offering",
    "PrivateProceedsRecord",
    "ProceedsRecord",
    "ProceedsUse",
    "PublicProceedsRecord",
    "Section",
    "ShareClassCounts",
    "ShareCountRecord",
    "ShareCounts",
    "TreasuryMovement",
    "TreasuryRecord",
    "capital_changes",
    "capital_structure",
    "change_category",
    "is_note",
    "latest_share_counts",
    "parse_share_counts",
    "period_share_counts",
    "proceeds_uses",
    "share_class",
    "treasury_methods",
    "treasury_totals",
]
