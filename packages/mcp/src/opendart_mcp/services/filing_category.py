"""Infer a filing's category from its title and number without another request."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.identifiers import filing_source
from opendart_analysis.domain.periods import parse_periodic_title

if TYPE_CHECKING:
    from opendart_analysis.domain.categories import FilingCategory

_PERIODIC: Final[dict[str, FilingCategory]] = {
    "annual": "annual_report",
    "semiannual": "semiannual_report",
    "quarterly": "quarterly_report",
}
_EXCHANGE_SOURCES: Final = frozenset({"krx_kospi", "krx_kosdaq", "krx_konex"})
# Official English form names that identify a category unambiguously in FSS filing titles.
_TITLE_CATEGORIES: Final[tuple[tuple[str, FilingCategory], ...]] = (
    ("significant holdings of stocks", "major_holding_report"),
    ("owned by executives and major shareholders", "insider_ownership_report"),
    ("trading plan", "insider_trading_plan"),
    ("tender offer", "tender_offer"),
    ("proxy", "proxy_solicitation"),
    ("major issues", "major_issues"),
    ("registration statement", "offerings"),
    ("audit report", "audit_reports"),
)


def infer_category(title: str, filing_number: str) -> FilingCategory | None:
    """Infer a category from what a filing reveals without another request.

    Args:
        title (str): Cleaned title.
        filing_number (str): 14-digit filing number.

    Returns:
        FilingCategory | None: Periodic-report subtype, exchange disclosure, a category named
            by an official form name in the title, or None.
    """
    periodic = parse_periodic_title(title)
    if periodic is not None:
        return _PERIODIC[periodic.kind]
    if filing_source(filing_number) in _EXCHANGE_SOURCES:
        return "exchange_disclosures"
    lowered = title.casefold()
    return next((category for phrase, category in _TITLE_CATEGORIES if phrase in lowered), None)
