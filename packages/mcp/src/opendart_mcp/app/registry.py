"""Register every component in a fixed order.

``tools/list`` follows registration order, and a stable order keeps model prompt caches
warm, so modules are listed here explicitly instead of discovered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opendart_mcp import apps, completions, prompts
from opendart_mcp.resources import (
    company as company_resources,
    filings as filing_resources,
    reference,
    status,
)
from opendart_mcp.tools import (
    calendar,
    capital,
    company,
    compare,
    debt,
    dividends,
    documents,
    events,
    filings,
    financials,
    governance,
    ownership,
    services,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from opendart_mcp.settings import Settings

TOOL_MODULES = (
    company,
    filings,
    documents,
    financials,
    compare,
    events,
    ownership,
    capital,
    debt,
    dividends,
    governance,
    calendar,
)
RESOURCE_MODULES = (company_resources, filing_resources, reference, status, apps)


def register_components(server: FastMCP[dict[str, Any]], settings: Settings) -> None:
    """Add tools, resources, prompts, and the completion handler to a server.

    Args:
        server (FastMCP[dict[str, Any]]): Server under construction.
        settings (Settings): Server configuration; enables the escape-hatch tools.
    """
    tool_modules = (
        (*TOOL_MODULES, services) if settings.tools.enable_service_tools else TOOL_MODULES
    )
    for module in tool_modules:
        for function in module.TOOLS:
            server.add_tool(function)
    for module in RESOURCE_MODULES:
        for function in module.RESOURCES:
            server.add_resource(function)
    for function in prompts.PROMPTS:
        server.add_prompt(function)
    if completions.HANDLER is not None:
        server.add_completion_handler(completions.HANDLER)
