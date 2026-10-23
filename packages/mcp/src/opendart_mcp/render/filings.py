"""Markdown view of filing searches."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from opendart_mcp.render.markdown import company_line, footer, join, table

if TYPE_CHECKING:
    from opendart_mcp.models.common import Pagination
    from opendart_mcp.models.filings import FilingItem, SearchFilingsResult

_COMPANY_HEADERS = ("Filed", "Title", "Category", "Filing number")
_MARKET_HEADERS = ("Filed", "Company", "Title", "Category", "Filing number")


def _title(filing: FilingItem) -> str:
    """Show a title with its amendment and remark flags.

    Args:
        filing (FilingItem): Filing.

    Returns:
        str: Title followed by bracketed flags.
    """
    flags = [
        name
        for name, present in (
            ("amendment", filing.is_amendment),
            ("corrected later", filing.corrected_later),
            ("withdrawn", filing.withdrawn),
        )
        if present
    ]
    return f"{filing.title} [{", ".join(flags)}]" if flags else filing.title


def _company(filing: FilingItem) -> str:
    """Name a filing's company with its stock code.

    Args:
        filing (FilingItem): Filing.

    Returns:
        str: For example "SAMSUNG ELECTRONICS (005930)".
    """
    company = filing.company
    if company is None:
        return "-"
    return f"{company.name} ({company.stock_code})" if company.stock_code else company.name


def _paging(pagination: Pagination, shown: int) -> str:
    """Describe the page shown and the call for the next one.

    Args:
        pagination (Pagination): Paging fields.
        shown (int): Filings on this page.

    Returns:
        str: One or two sentences, or an empty string for an empty page.
    """
    if not shown:
        return ""
    first = (pagination.page - 1) * pagination.limit + 1
    of = f" of {pagination.total:,}" if pagination.total is not None else ""
    text = f"Showing {first:,}-{first + shown - 1:,}{of}."
    if pagination.next_call is not None:
        arguments = json.dumps(pagination.next_call.arguments, ensure_ascii=False)
        text += f" Next page: {pagination.next_call.tool} {arguments}"
    return text


def render_search_filings(result: SearchFilingsResult) -> str:
    """Render a filing search.

    Args:
        result (SearchFilingsResult): Search result.

    Returns:
        str: Markdown.
    """
    scope = company_line(result.company) if result.company else "all companies"
    heading = f"**Filings, {scope}: {result.since.isoformat()} to {result.until.isoformat()}**"
    rows: list[tuple[object, ...]]
    headers: tuple[str, ...]
    if result.company is not None:
        rows = [(f.filed, _title(f), f.category, f.filing_number) for f in result.filings]
        headers = _COMPANY_HEADERS
    else:
        rows = [
            (f.filed, _company(f), _title(f), f.category, f.filing_number) for f in result.filings
        ]
        headers = _MARKET_HEADERS
    return join(
        heading,
        table(headers, rows),
        _paging(result.pagination, len(result.filings)),
        footer(result),
    )
