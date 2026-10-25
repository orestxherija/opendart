"""Friendly filing categories over OpenDART's disclosure type codes.

``disclosures.search`` filters by ``pblntf_ty`` (ten groups, A to J) and optionally
``pblntf_detail_ty`` (subtypes such as A001, the annual report). Callers use friendly names
instead, mapped here, and ``CATEGORY_INFO`` describes each one.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from collections.abc import Mapping

FilingCategory = Literal[
    "periodic_reports",
    "annual_report",
    "semiannual_report",
    "quarterly_report",
    "major_issues",
    "offerings",
    "equity_offering",
    "debt_offering",
    "merger_offering",
    "equity_disclosures",
    "major_holding_report",
    "insider_ownership_report",
    "proxy_solicitation",
    "tender_offer",
    "insider_trading_plan",
    "other_disclosures",
    "treasury_stock",
    "treasury_trust",
    "merger_completion",
    "stock_options",
    "outside_directors",
    "shareholder_meeting",
    "audit_reports",
    "funds",
    "asset_backed",
    "exchange_disclosures",
    "ad_hoc_disclosure",
    "fair_disclosure",
    "market_notices",
    "fair_trade_commission",
]
"""Friendly filing category names accepted by filing searches."""

FILING_CATEGORIES: tuple[FilingCategory, ...] = get_args(FilingCategory)
"""Every category, in documentation order."""


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    """Upstream codes and a description for one filing category.

    Attributes:
        name (FilingCategory): Friendly name.
        group (str): ``pblntf_ty``, A to J.
        subtype (str | None): ``pblntf_detail_ty``, or None for the whole group.
        description (str): English description of the category.
    """

    name: FilingCategory
    group: str
    subtype: str | None
    description: str


_CATEGORIES = (
    CategoryInfo(
        "periodic_reports", "A", None, "All periodic reports: annual, half-year, and quarterly."
    ),
    CategoryInfo(
        "annual_report",
        "A",
        "A001",
        "Annual (business) report, due 90 days after the fiscal year end.",
    ),
    CategoryInfo(
        "semiannual_report", "A", "A002", "Half-year report, due 45 days after the half-year end."
    ),
    CategoryInfo(
        "quarterly_report",
        "A",
        "A003",
        "First- and third-quarter reports, due 45 days after the quarter end.",
    ),
    CategoryInfo(
        "major_issues",
        "B",
        None,
        "Major-issue reports: capital raises, convertible bonds, buybacks, M&A, asset deals, defaults, lawsuits.",
    ),
    CategoryInfo(
        "offerings", "C", None, "Securities registration statements and other issuance disclosures."
    ),
    CategoryInfo(
        "equity_offering", "C", "C001", "Securities registration statement for equity securities."
    ),
    CategoryInfo(
        "debt_offering", "C", "C002", "Securities registration statement for debt securities."
    ),
    CategoryInfo(
        "merger_offering",
        "C",
        "C004",
        "Securities registration statement for a merger, split, or share swap.",
    ),
    CategoryInfo(
        "equity_disclosures",
        "D",
        None,
        "Ownership disclosures: 5% holders, insiders, proxy solicitations, tender offers.",
    ),
    CategoryInfo(
        "major_holding_report", "D", "D001", "Report on significant holdings (the 5% rule)."
    ),
    CategoryInfo(
        "insider_ownership_report",
        "D",
        "D002",
        "Report on shares owned by executives and major shareholders.",
    ),
    CategoryInfo("proxy_solicitation", "D", "D003", "Proxy solicitation reference documents."),
    CategoryInfo("tender_offer", "D", "D004", "Tender offer statements and reports."),
    CategoryInfo(
        "insider_trading_plan", "D", "D005", "Trading plans of executives and major shareholders."
    ),
    CategoryInfo(
        "other_disclosures",
        "E",
        None,
        "Other FSS disclosures: treasury stock, trusts, mergers, stock options, directors, meetings.",
    ),
    CategoryInfo("treasury_stock", "E", "E001", "Acquisition or disposal of treasury stock."),
    CategoryInfo(
        "treasury_trust", "E", "E002", "Treasury-stock trust contracts entered or terminated."
    ),
    CategoryInfo(
        "merger_completion",
        "E",
        "E003",
        "Report on the completion of a merger or similar transaction.",
    ),
    CategoryInfo("stock_options", "E", "E004", "Report on granting stock options."),
    CategoryInfo("outside_directors", "E", "E005", "Report on outside (independent) directors."),
    CategoryInfo("shareholder_meeting", "E", "E006", "Notice calling a shareholders' meeting."),
    CategoryInfo(
        "audit_reports",
        "F",
        None,
        "External audit reports, including consolidated and combined audit reports.",
    ),
    CategoryInfo("funds", "G", None, "Collective investment (fund) securities registrations."),
    CategoryInfo(
        "asset_backed", "H", None, "Asset-backed securitization plans, registrations, and reports."
    ),
    CategoryInfo(
        "exchange_disclosures",
        "I",
        None,
        "KRX disclosures: ad hoc and fair disclosures, market notices, and others.",
    ),
    CategoryInfo(
        "ad_hoc_disclosure",
        "I",
        "I001",
        "KRX ad hoc (timely) disclosures, such as supply contracts and board decisions.",
    ),
    CategoryInfo(
        "fair_disclosure",
        "I",
        "I002",
        "KRX fair disclosures, such as preliminary earnings and guidance.",
    ),
    CategoryInfo(
        "market_notices",
        "I",
        "I003",
        "KRX market measures and notices, such as trading halts and designations.",
    ),
    CategoryInfo(
        "fair_trade_commission",
        "J",
        None,
        "Fair Trade Commission disclosures, such as large internal transactions.",
    ),
)

CATEGORY_INFO: Mapping[FilingCategory, CategoryInfo] = MappingProxyType(
    {info.name: info for info in _CATEGORIES}
)
"""Every category's upstream codes and description, in documentation order."""


def category_query(category: FilingCategory) -> tuple[str, str | None]:
    """Return the search parameters for a category.

    Args:
        category (FilingCategory): Friendly category name.

    Returns:
        tuple[str, str | None]: ``pblntf_ty`` and ``pblntf_detail_ty`` (None for a group).

    Raises:
        ValueError: The name is not a known category.
    """
    info = CATEGORY_INFO.get(category)
    if info is None:
        msg = f"Unknown filing category {category!r}; use one of: {", ".join(FILING_CATEGORIES)}"
        raise ValueError(msg)
    return info.group, info.subtype
