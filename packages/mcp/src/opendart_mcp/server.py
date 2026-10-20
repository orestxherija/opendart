"""Minimal MCP server; OpenDART tools will be registered here."""

from mcp.server import MCPServer

server = MCPServer("OpenDART")


def main() -> None:
    """Serve MCP requests over stdin and stdout."""
    server.run(transport="stdio")
