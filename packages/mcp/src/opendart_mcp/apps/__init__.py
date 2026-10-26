"""MCP Apps: self-contained HTML views of tool results, served as ``ui://`` resources.

Hosts that support the MCP Apps extension render the results of ``get_financials``,
``compare_companies``, and ``get_corporate_action_calendar`` with these pages. Other hosts
ignore the link and show the tools' text and structured content unchanged.
"""

from __future__ import annotations

from opendart_mcp.apps.resources import RESOURCES

__all__ = ["RESOURCES"]
