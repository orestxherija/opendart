"""Markdown views of the service catalog and of direct service calls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.render.markdown import MISSING_VALUE, escape, footer, join, section, table

if TYPE_CHECKING:
    from opendart_mcp.models.services import (
        Cell,
        ServiceCallResult,
        ServiceInfo,
        ServiceListResult,
        ServiceTable,
    )

_NUMERIC_KINDS: Final = frozenset({"amount", "per_share", "count", "number", "ratio", "percent"})
_UNITS: Final = "Amounts are exact won, percentages are in percent units, and dates are ISO."


def _params(info: ServiceInfo) -> str:
    """Summarize a service's parameters.

    Args:
        info (ServiceInfo): Catalog entry.

    Returns:
        str: Parameters with required ones starred and their accepted values.
    """
    parts = [f"{p.wire}{"*" if p.required else ""} ({p.accepts})" for p in info.params]
    return "; ".join(parts) or "none"


def render_service_list(result: ServiceListResult) -> str:
    """Render catalog matches.

    Args:
        result (ServiceListResult): Search result.

    Returns:
        str: Markdown.
    """
    scope = f'matching "{result.query}"' if result.query else "available to call_service"
    shown = f" ({len(result.services)} of {result.total})" if result.services else ""
    rows = [(s.service, s.title, _params(s), s.covered_by) for s in result.services]
    legend = (
        "Parameters marked * are required. Prefer the covering tool when one is listed."
        if result.services
        else ""
    )
    return join(
        f"**OpenDART services {scope}**{shown}",
        table(("Service", "Title", "Parameters", "Covered by"), rows),
        legend,
        footer(result),
    )


def _cell(value: Cell) -> str:
    """Format one normalized value for a table cell.

    Args:
        value (Cell): Normalized value.

    Returns:
        str: Text, with thousands separators for numbers.
    """
    if value is None:
        return MISSING_VALUE
    if isinstance(value, int | float):
        return f"{value:,}"
    return value


def _table(service_table: ServiceTable) -> str:
    """Render one table of a service response.

    Args:
        service_table (ServiceTable): Labeled, normalized rows.

    Returns:
        str: Shared values as a list, then the rows as a table.
    """
    shared = "\n".join(
        f"- {label}: {escape(_cell(value))}"
        for label, value in (service_table.common or {}).items()
    )
    columns = service_table.columns
    numeric = [i for i, column in enumerate(columns) if column.kind in _NUMERIC_KINDS]
    rows = [[_cell(value) for value in row] for row in service_table.rows]
    grid = table([c.label for c in columns], rows, numeric=numeric) if columns else ""
    body = join(shared, grid)
    return section(service_table.section, body) if service_table.section else body


def _paging(result: ServiceCallResult) -> str:
    """Describe which rows are shown.

    Args:
        result (ServiceCallResult): Call result.

    Returns:
        str: Row range and the next page, or an empty string for one page.
    """
    paging = result.pagination
    if not paging.total or (paging.page == 1 and not paging.has_more):
        return ""
    first = (paging.page - 1) * paging.limit + 1
    last = min(paging.page * paging.limit, paging.total)
    more = f" Next: call_service with page={paging.page + 1}." if paging.has_more else ""
    return f"Rows {first}-{last} of {paging.total}.{more}"


def render_service_call(result: ServiceCallResult) -> str:
    """Render the records of a service call.

    Args:
        result (ServiceCallResult): Call result.

    Returns:
        str: Markdown.
    """
    sent = ", ".join(
        f"{name}={",".join(value) if isinstance(value, list) else value}"
        for name, value in result.params.items()
    )
    has_rows = any(t.rows for t in result.tables)
    return join(
        f"**{result.service}: {result.title}**",
        f"Parameters: {sent}" if sent else "",
        *(_table(t) for t in result.tables),
        _paging(result),
        _UNITS if has_rows else "",
        footer(result),
    )
