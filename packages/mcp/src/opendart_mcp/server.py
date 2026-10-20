"""Minimal MCP server for testing local and container deployments."""

from mcp.server import MCPServer

server = MCPServer("OpenDART")


@server.tool()
def ping() -> str:
    """Check that the MCP server can handle tool calls.

    Returns:
        str: The literal response ``pong``.
    """
    return "pong"


def main() -> None:
    """Serve MCP requests over stdin and stdout."""
    server.run(transport="stdio")
