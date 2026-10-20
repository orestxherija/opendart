"""Smoke-test a stdio MCP server, locally or through a Docker command."""

import argparse
import sys

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def check(command: list[str]) -> None:
    """Initialize the server, discover its ping tool, and verify its response.

    Args:
        command (list[str]): Executable and arguments used to start the server.
    """
    parameters = StdioServerParameters(command=command[0], args=command[1:])
    with anyio.fail_after(60):
        async with Client(parameters) as client:
            tools = await client.list_tools()
            if "ping" not in {tool.name for tool in tools.tools}:
                raise RuntimeError("The server did not advertise the ping tool")
            result = await client.call_tool("ping", {})
            if result.is_error or not any(
                content.type == "text" and content.text == "pong" for content in result.content
            ):
                raise RuntimeError(f"Expected pong from ping, received {result}")
    print("MCP smoke test passed: ping -> pong")


def main() -> None:
    """Run the smoke test against the given command or the local package."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Server command; defaults to python -m opendart_mcp",
    )
    args = parser.parse_args()
    command = args.command or [sys.executable, "-m", "opendart_mcp"]
    anyio.run(check, command)


if __name__ == "__main__":
    main()
