"""Markdown view of the corporate-action calendar: one table row per dated action."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.render.events import action_label, plural
from opendart_mcp.render.markdown import footer, join, number, table

if TYPE_CHECKING:
    from opendart_mcp.models.calendar import CalendarResult, DetailValue
    from opendart_mcp.models.common import CompanyRef

_LABELS: Final = {"debt_maturity": "Debt maturity"}
"""Labels of calendar actions that no event report files."""


def _action(code: str) -> str:
    """Label an action code.

    Args:
        code (str): Action code, such as record_date or debt_maturity.

    Returns:
        str: English label.
    """
    return _LABELS.get(code) or action_label(code)


def _company(company: CompanyRef) -> str:
    """Name a company compactly.

    Args:
        company (CompanyRef): Company.

    Returns:
        str: Name with the stock code, or the corp code for unlisted companies.
    """
    return f"{company.name} ({company.stock_code or company.corp_code})"


def _value(value: DetailValue) -> str:
    """Format a detail value.

    Args:
        value (DetailValue): Detail value.

    Returns:
        str: Numbers with thousands separators, other values as text.
    """
    if isinstance(value, int | float):
        return number(value, decimals=0 if isinstance(value, int) else 2)
    return "-" if value is None else value


def _terms(details: dict[str, DetailValue]) -> str:
    """List an item's key terms.

    Args:
        details (dict[str, DetailValue]): Item details.

    Returns:
        str: For example "face_value 5,000,000,000; coupon_pct 2.00".
    """
    return "; ".join(f"{key} {_value(value)}" for key, value in details.items() if key != "event")


def render_calendar(result: CalendarResult) -> str:
    """Render the corporate-action calendar.

    Args:
        result (CalendarResult): Calendar result.

    Returns:
        str: Markdown.
    """
    rows = [
        (
            item.date,
            _company(item.company),
            _action(item.action),
            item.details.get("event", item.source_kind),
            _terms(item.details),
            item.filing_number,
        )
        for item in result.items
    ]
    headers = ("Date", "Company", "Action", "Event", "Terms", "Filing")
    companies = plural(len(result.companies), "company", "companies")
    scope = f"{companies}, {plural(len(result.items), "date")}, horizon {plural(result.horizon_days, "day")}."
    return join(
        f"**Corporate-action calendar: {result.start} to {result.end}**",
        scope,
        table(headers, rows),
        footer(result),
    )
