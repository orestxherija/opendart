"""Smoke-test a local HTTP MCP server or start an isolated native server."""

from __future__ import annotations

import argparse
import os
import socket
import sys
from urllib.parse import urlsplit

import anyio
from mcp import Client


async def check(url: str) -> None:
    """Initialize the server, discover its ping tool, and verify its response.

    Args:
        url (str): Local Streamable HTTP endpoint to test.
    """
    endpoint = urlsplit(url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("The smoke test requires an HTTP endpoint on localhost")
    with anyio.fail_after(60):
        # Wait for startup without replaying protocol operations or tool calls.
        while True:
            try:
                async with await anyio.connect_tcp(endpoint.hostname, endpoint.port or 80):
                    break
            except OSError:
                await anyio.sleep(0.1)
        for mode in ("auto", "legacy"):
            async with Client(url, mode=mode) as client:
                tools = await client.list_tools()
                if "ping" not in {tool.name for tool in tools.tools}:
                    raise RuntimeError("The server did not advertise the ping tool")
                result = await client.call_tool("ping", {})
                if result.is_error or not any(
                    content.type == "text" and content.text == "pong" for content in result.content
                ):
                    raise RuntimeError(f"Expected pong from ping, received {result}")
    print("MCP smoke test passed: ping -> pong")


async def check_native() -> None:
    """Start a server on an unused loopback port and clean it up after testing."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ,
        "OPENDART_MCP_HTTP__HOST": "127.0.0.1",
        "OPENDART_MCP_HTTP__PORT": str(port),
    }
    async with await anyio.open_process(
        [sys.executable, "-m", "opendart_mcp"],
        env=environment,
        stdout=sys.stderr,
        stderr=sys.stderr,
    ) as process:
        try:
            await check(f"http://127.0.0.1:{port}/mcp")
        finally:
            if process.returncode is None:
                process.terminate()
                with anyio.move_on_after(5):
                    await process.wait()
                if process.returncode is None:
                    process.kill()
                    await process.wait()


def main() -> None:
    """Test a running HTTP endpoint or launch an isolated native server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        help="Running localhost MCP URL; omit to start and stop an isolated native server",
    )
    args = parser.parse_args()
    if args.url:
        anyio.run(check, args.url)
    else:
        anyio.run(check_native)


if __name__ == "__main__":
    main()
