"""Filing discovery: search OpenDART's filing index by company, market, category, and title.

``find_filings`` serves one slice of a search, newest first, through a caller-supplied
``ReadFilingPage`` that reads one upstream page. Several categories, or a title filter, are
merged over a bounded number of page reads:

    window = DateWindow(date(2026, 9, 1), date(2026, 10, 22))
    request = FilingSearchRequest("00126380", window, categories=("major_issues",))
    results = await find_filings(request, read_page=read_page)

Data access follows ``opendart_analysis.upstream``. Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.domain.categories import CATEGORY_INFO, FILING_CATEGORIES, FilingCategory
from opendart_analysis.filings.access import (
    CorporationType,
    FilingPage,
    FilingPageQuery,
    ListedFiling,
    Progress,
    ReadFilingPage,
    no_progress,
)
from opendart_analysis.filings.category import category_codes, disjoint_categories, infer_category
from opendart_analysis.filings.scan import Filing, filing_from
from opendart_analysis.filings.search import (
    MAX_CALLS,
    TITLE_SCAN_CALLS,
    FilingResults,
    FilingSearchRequest,
    SearchBudgetError,
    TitleScan,
    find_filings,
)

__all__ = [
    "CATEGORY_INFO",
    "FILING_CATEGORIES",
    "MAX_CALLS",
    "TITLE_SCAN_CALLS",
    "CorporationType",
    "Filing",
    "FilingCategory",
    "FilingPage",
    "FilingPageQuery",
    "FilingResults",
    "FilingSearchRequest",
    "ListedFiling",
    "Progress",
    "ReadFilingPage",
    "SearchBudgetError",
    "TitleScan",
    "category_codes",
    "disjoint_categories",
    "filing_from",
    "find_filings",
    "infer_category",
    "no_progress",
]
