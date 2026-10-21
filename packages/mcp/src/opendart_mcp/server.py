"""Minimal MCP server for testing local and container deployments."""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from opendart_mcp.settings import get_settings

server = MCPServer("OpenDART")


@server.tool()
def ping() -> str:
    """Check that the MCP server can handle tool calls.

    Returns:
        str: The literal response ``pong``.
    """
    return "pong"


def main() -> None:
    """Serve MCP requests over Streamable HTTP on the local machine."""
    settings = get_settings().http
    server.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        streamable_http_path="/mcp",
        # Keep localhost protections enabled when Docker needs a wildcard bind.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )
