"""Ownership and control: the controlling group, changes of control, and holding reports.

``ownership_report`` reads the control snapshot from one periodic report: the largest
shareholder and related parties, the group's stake in the voting class, minority
shareholders, treasury shares, and a free-float estimate, with changes of the largest
shareholder. ``holding_reports`` reads the 5% holder and insider ownership reports filed in a
window. Both take the upstream tables they need as keyword-only callables, following
``opendart_analysis.upstream``:

    resolved = await resolve_period(
        company, period="latest", fiscal_year=None, search_filings=search, today=today
    )
    report = await ownership_report(company, resolved, fetch_largest_holders=..., today=today)

Percentages are floats in percent of the holding class's issued shares, as filed; share
counts are integers. Share counts by class come from ``opendart_analysis.capital``. Modules:
``control`` (the snapshot), ``tables`` (control changes and minority shareholders),
``report`` (the periodic-report workflow), ``holdings`` (holding reports), and
``holding_access`` (their data access). Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.ownership.control import (
    LARGEST,
    RELATIONS,
    ControlSnapshot,
    FetchLargestHolders,
    Holder,
    LargestHolderRecord,
    control_snapshot,
    free_float,
    relation,
)
from opendart_analysis.ownership.holding_access import (
    FetchInsiderHoldings,
    FetchMajorHoldings,
    HoldingQuery,
    InsiderHoldingRecord,
    MajorHoldingRecord,
)
from opendart_analysis.ownership.holdings import (
    LISTING_MONTHS,
    HoldingReports,
    InsiderReport,
    MajorHolderReport,
    ReportActivity,
    activity,
    holding_reports,
    predates_listings,
)
from opendart_analysis.ownership.report import OwnershipReport, ownership_report
from opendart_analysis.ownership.tables import (
    ControlChange,
    ControlChangeRecord,
    FetchControlChanges,
    FetchMinorityHolders,
    MinorityHolders,
    MinorityRecord,
    control_changes,
    minority_holders,
)

__all__ = [
    "LARGEST",
    "LISTING_MONTHS",
    "RELATIONS",
    "ControlChange",
    "ControlChangeRecord",
    "ControlSnapshot",
    "FetchControlChanges",
    "FetchInsiderHoldings",
    "FetchLargestHolders",
    "FetchMajorHoldings",
    "FetchMinorityHolders",
    "Holder",
    "HoldingQuery",
    "HoldingReports",
    "InsiderHoldingRecord",
    "InsiderReport",
    "LargestHolderRecord",
    "MajorHolderReport",
    "MajorHoldingRecord",
    "MinorityHolders",
    "MinorityRecord",
    "OwnershipReport",
    "ReportActivity",
    "activity",
    "control_changes",
    "control_snapshot",
    "free_float",
    "holding_reports",
    "minority_holders",
    "ownership_report",
    "predates_listings",
    "relation",
]
