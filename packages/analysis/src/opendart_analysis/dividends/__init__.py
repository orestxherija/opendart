"""Dividend history by measure, share class, and fiscal year, from annual reports.

The workflow takes a company, its annual candidate periods from
``opendart_analysis.reports.resolve_period``, and a ``FetchService`` for the dividend table
(``alot_matter``), following ``opendart_analysis.upstream``:

    resolved = await resolve_period(
        company, period="FY", fiscal_year=None, search_filings=search, today=today
    )
    history = await dividend_history(
        company, resolved, years=5, fetch_service=fetch, today=today
    )

Rows hold cash and stock dividends per share and in total, the payout ratio, yields as filed,
and the net income, EPS, and par value they rest on, with values converted from the filed unit
(totals filed in KRW million become won). Modules: ``rows`` (classification, units, merging
across reports) and ``history`` (the workflow). Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.dividends.history import (
    MAX_YEARS,
    SERVICE,
    YEARS_PER_REPORT,
    YIELD_NOTE,
    DividendHistory,
    dividend_history,
)
from opendart_analysis.dividends.rows import (
    MEASURES,
    DividendMeasure,
    DividendRow,
    EarningsBasis,
    ValueUnit,
    basis,
    measure,
    merge,
    share_class,
    unit,
    value,
)

__all__ = [
    "MAX_YEARS",
    "MEASURES",
    "SERVICE",
    "YEARS_PER_REPORT",
    "YIELD_NOTE",
    "DividendHistory",
    "DividendMeasure",
    "DividendRow",
    "EarningsBasis",
    "ValueUnit",
    "basis",
    "dividend_history",
    "measure",
    "merge",
    "share_class",
    "unit",
    "value",
]
