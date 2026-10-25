"""Periodic-report extracts: one service, one company, one reporting period.

Thirty OpenDART services return tables from periodic reports, such as dividends, shareholders,
executives, and debt securities. This package fetches them through a caller-supplied
``FetchService``, runs several fetches at once, reads their all-string fields safely, and
describes the filings the records came from:

    resolved = await resolve_period(company, period="FY", fiscal_year=None, ...)
    found = await first_available(
        resolved,
        lambda ref: fetch_records(
            "alot_matter", company=company, ref=ref, fetch_service=fetch, today=today
        ),
        attempts=probe_attempts(resolved),
    )

Data access and the clock are explicit inputs, following ``opendart_analysis.upstream``.
Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.extracts.fetch import (
    PERIODIC_PARAMS,
    FilingSource,
    checked,
    fetch_records,
    fetch_response,
    gather_all,
    probe_attempts,
    sources,
)
from opendart_analysis.extracts.fields import (
    amount,
    filed_text,
    fold,
    is_total,
    records,
    term_ages,
    text,
)

__all__ = [
    "PERIODIC_PARAMS",
    "FilingSource",
    "amount",
    "checked",
    "fetch_records",
    "fetch_response",
    "filed_text",
    "fold",
    "gather_all",
    "is_total",
    "probe_attempts",
    "records",
    "sources",
    "term_ages",
    "text",
]
