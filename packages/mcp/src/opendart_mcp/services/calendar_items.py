"""Project calendar items between ``opendart_analysis.calendar`` and the output model.

Turning event records and debt maturities into items, merging the dates that a registration
statement repeats from its decision, and replacing event maturities with debt maturities live
in ``opendart_analysis.calendar.items``. This module attaches the company's identity and the
DART viewer link to each analysis item, turns items from a maturity provider back into
analysis items so they merge like the server's own, and describes resolved companies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis import calendar
from opendart_analysis.domain.identifiers import dart_viewer_url
from opendart_mcp.models.calendar import CalendarItem

if TYPE_CHECKING:
    from opendart_mcp.services.companies import Company


def output_item(item: calendar.CalendarItem, company: Company) -> CalendarItem:
    """Describe one analysis item.

    Args:
        item (calendar.CalendarItem): Item from ``opendart_analysis.calendar``.
        company (Company): The item's company.

    Returns:
        CalendarItem: Output item linking to the filing in the DART viewer.
    """
    return CalendarItem(
        date=item.date,
        company=company.ref,
        action=item.action,
        source_kind=item.source_kind,
        filing_number=item.filing_number,
        dart_url=dart_viewer_url(item.filing_number),
        details=dict(item.details),
    )


def analysis_item(item: CalendarItem, company: Company) -> calendar.CalendarItem:
    """Turn an output item, such as a maturity provider's, into an analysis item.

    Args:
        item (CalendarItem): Output item.
        company (Company): Company whose calendar the item joins.

    Returns:
        calendar.CalendarItem: The same date, action, source, filing, and details.
    """
    return calendar.CalendarItem(
        item.date,
        company.corp_code,
        item.action,
        item.source_kind,
        item.filing_number,
        dict(item.details),
    )


def subject(company: Company) -> calendar.CalendarSubject:
    """Describe a resolved company for ``opendart_analysis.calendar``.

    Args:
        company (Company): Resolved company.

    Returns:
        calendar.CalendarSubject: Corporation code, English and Korean names, and fiscal year-end.
    """
    ref = company.ref
    return calendar.CalendarSubject(
        ref.corp_code, ref.name, korean_name=ref.korean_name, fye_month=company.fye_month
    )
