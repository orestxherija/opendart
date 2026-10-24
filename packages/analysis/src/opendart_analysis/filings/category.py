"""Filing categories: upstream search codes, disjoint requests, and inference from a title.

Upstream quirk, verified live: ``pblntf_detail_ty`` filters only when ``pblntf_ty`` is
omitted. Sent together, the subtype is ignored and the whole group comes back, so subtype
categories send the subtype alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from opendart_analysis.domain.categories import CATEGORY_INFO, category_query
from opendart_analysis.domain.identifiers import filing_source
from opendart_analysis.domain.periods import parse_periodic_title

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.domain.categories import FilingCategory
    from opendart_analysis.upstream import DisclosureGroup

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


def category_codes(category: FilingCategory | None) -> tuple[DisclosureGroup | None, str | None]:
    """Return ``pblntf_ty`` and ``pblntf_detail_ty`` for a category.

    Subtypes are sent without their group, because OpenDART ignores a subtype sent with one.

    Args:
        category (FilingCategory | None): Category, or None for every filing.

    Returns:
        tuple[DisclosureGroup | None, str | None]: Group and subtype codes, either possibly
            None.
    """
    if category is None:
        return None, None
    group, subtype = category_query(category)
    return (None, subtype) if subtype else (cast("DisclosureGroup", group), None)


def disjoint_categories(
    categories: Sequence[FilingCategory],
) -> tuple[FilingCategory | None, ...]:
    """Drop repeated categories and subtypes whose group is also requested.

    Args:
        categories (Sequence[FilingCategory]): Requested categories; empty for all.

    Returns:
        tuple[FilingCategory | None, ...]: Disjoint categories, or ``(None,)`` for all filings.
    """
    if not categories:
        return (None,)
    unique = list(dict.fromkeys(categories))
    groups = {CATEGORY_INFO[c].group for c in unique if CATEGORY_INFO[c].subtype is None}
    return tuple(
        c
        for c in unique
        if CATEGORY_INFO[c].subtype is None or CATEGORY_INFO[c].group not in groups
    )
