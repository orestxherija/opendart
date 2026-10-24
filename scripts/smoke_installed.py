#!/usr/bin/env python3
"""Probe installed SDK and MCP distributions using an isolated interpreter outside the checkout."""

from __future__ import annotations

import argparse
import asyncio
import os
import runpy
import socket
import sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path


def require(condition: object, message: str) -> None:
    """Keep smoke assertions active even when PYTHONOPTIMIZE is configured."""
    if not condition:
        raise RuntimeError(message)


async def check_sdk() -> None:
    """Import the SDK's generated resources and perform one request using a mock transport."""
    import httpx2

    from opendart import OpenDART, OpenDARTSettings

    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, json={"status": "000", "message": "OK"})

    settings = OpenDARTSettings(api_key="0" * 40)
    async with OpenDART(settings, transport=httpx2.MockTransport(respond)) as client:
        response = await client.disclosures.search()
        require(response.status == "000", "SDK did not parse the synthetic response")
    require(len(requests) == 1 and client.is_closed, "SDK request or cleanup failed")
    require(files("opendart").joinpath("py.typed").is_file(), "SDK typing marker is missing")


async def check_mcp() -> None:
    """Launch the installed console script and reuse the localhost HTTP protocol/security probe."""
    import anyio

    # Loading a single trusted probe does not add the checkout to the isolated interpreter's path.
    check = runpy.run_path(str(Path(__file__).with_name("check_mcp.py")))["check"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = Path(sys.executable).with_name(
        "opendart-mcp.exe" if os.name == "nt" else "opendart-mcp"
    )
    environment = {
        **{key: value for key, value in os.environ.items() if not key.startswith("OPENDART_")},
        "OPENDART_MCP_HTTP__HOST": "127.0.0.1",
        "OPENDART_MCP_HTTP__PORT": str(port),
    }
    async with await anyio.open_process(
        [str(command)], env=environment, stdout=sys.stderr, stderr=sys.stderr
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
    """Validate the SDK alone, or both packages and the installed MCP console entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sdk-only", action="store_true")
    args = parser.parse_args()
    require(sys.flags.isolated, "Run this probe with python -I to exclude checkout imports")
    require(version("opendart-sdk") == args.version, "Wrong SDK distribution version")
    asyncio.run(check_sdk())
    if not args.sdk_only:
        require(version("opendart-mcp") == args.version, "Wrong MCP distribution version")
        asyncio.run(check_mcp())
    print(
        f"installed {"SDK" if args.sdk_only else "SDK and MCP"} {args.version}: smoke check passed"
    )


if __name__ == "__main__":
    main()
