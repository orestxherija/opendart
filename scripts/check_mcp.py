"""Smoke-test a local HTTP MCP server or start an isolated native server.

Checks, over real HTTP: hostile Host and Origin headers are rejected; both protocol eras
(2026-07-28 discovery and the 2025-11-25 handshake) list every default tool recorded in
packages/mcp/components.lock.json; GET /health answers; the vocabulary resource reads; and
find_company either answers or explains what is missing (no API key, directory loading).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx2
from mcp import Client

LOCK = Path(__file__).resolve().parents[1] / "packages/mcp/components.lock.json"
# Used when the lock is unavailable, for example from an installed distribution.
FALLBACK_TOOLS = frozenset({"find_company", "get_company_profile"})
VOCABULARY = "opendart://reference/vocabulary"
# Errors the model can act on when find_company cannot answer from this server.
ACTIONABLE_ERRORS = {
    "OPENDART_API__API_KEY": "the missing API key is explained",
    "company directory": "the loading company directory is explained",
}


def expected_tools(lock: Path = LOCK) -> frozenset[str]:
    """Read the default (non-optional) tool names from the component lock.

    Args:
        lock: Component lock written by scripts/check_mcp_components.py.

    Returns:
        Tool names every server must list.
    """
    try:
        components = json.loads(lock.read_text(encoding="utf-8"))["components"].values()
    except OSError, ValueError, KeyError, AttributeError:
        return FALLBACK_TOOLS
    names = {c["name"] for c in components if c["kind"] == "tool" and not c.get("optional")}
    return frozenset(names) or FALLBACK_TOOLS


async def check_transport_security(url: str) -> None:
    """Reject requests with hostile Host or Origin headers through the real listener."""
    async with httpx2.AsyncClient(trust_env=False, timeout=5) as client:
        for headers, expected in (
            ({"Host": "attacker.invalid"}, 421),
            ({"Origin": "https://attacker.invalid"}, 403),
        ):
            response = await client.post(url, headers=headers, json={})
            if response.status_code != expected:
                raise RuntimeError(
                    f"Transport security check expected HTTP {expected}, received "
                    f"{response.status_code}"
                )


async def check_health(url: str) -> str:
    """Require GET /health to answer 200 with status ok.

    Args:
        url: MCP endpoint; /health is a sibling path.

    Returns:
        The reported server version.
    """
    health = url.removesuffix("/").removesuffix("/mcp") + "/health"
    async with httpx2.AsyncClient(trust_env=False, timeout=5) as client:
        response = await client.get(health)
    body: Any = response.json() if response.status_code == httpx2.codes.OK else None
    if not isinstance(body, dict) or body.get("status") != "ok":
        raise RuntimeError(f"Expected a healthy {health}, received HTTP {response.status_code}")
    return str(body.get("version", "unknown"))


def find_company_outcome(result: Any) -> str:
    """Accept a find_company answer or an actionable explanation of why there is none.

    Args:
        result: The tool call result.

    Returns:
        What happened.
    """
    texts = [content.text for content in result.content if content.type == "text"]
    if not result.is_error:
        matches = (result.structured_content or {}).get("matches")
        if isinstance(matches, list):
            return f"find_company returned {len(matches)} matches"
    for marker, outcome in ACTIONABLE_ERRORS.items():
        if result.is_error and any(marker in text for text in texts):
            return outcome
    raise RuntimeError(f"Unexpected find_company result: {result}")


async def check_vocabulary(client: Client) -> str:
    """Read the vocabulary resource when the server lists it.

    Args:
        client: Connected MCP client.

    Returns:
        What happened.
    """
    listed = await client.list_resources()
    if VOCABULARY not in {str(resource.uri) for resource in listed.resources}:
        return "vocabulary resource not listed (skipped)"
    contents = (await client.read_resource(VOCABULARY)).contents
    if not any(getattr(item, "text", "") for item in contents):
        raise RuntimeError(f"{VOCABULARY} returned no text")
    return "vocabulary resource read"


async def check_protocol(url: str, mode: str, expected: frozenset[str]) -> list[str]:
    """Discover tools and call find_company in one protocol era.

    Args:
        url: MCP endpoint.
        mode: ``auto`` (2026-07-28 when available) or ``legacy`` (2025-11-25).
        expected: Tool names the server must list.

    Returns:
        Outcomes worth reporting.
    """
    async with Client(url, mode=mode) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        missing = sorted(expected - names)
        if missing:
            raise RuntimeError(f"{mode}: the server did not list {", ".join(missing)}")
        outcome = find_company_outcome(
            await client.call_tool("find_company", {"query": "Samsung Electronics"})
        )
        vocabulary = await check_vocabulary(client)
    return [f"{mode}: {len(names)} tools", outcome, vocabulary]


async def check(url: str) -> None:
    """Check transport security, health, discovery, a resource, and a tool call.

    Args:
        url (str): Local Streamable HTTP endpoint to test.
    """
    endpoint = urlsplit(url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("The smoke test requires an HTTP endpoint on localhost")
    expected = expected_tools()
    with anyio.fail_after(120):
        # Wait for startup without replaying protocol operations or tool calls.
        while True:
            try:
                async with await anyio.connect_tcp(endpoint.hostname, endpoint.port or 80):
                    break
            except OSError:
                await anyio.sleep(0.1)
        await check_transport_security(url)
        version = await check_health(url)
        outcomes = [f"/health ok (version {version})"]
        for mode in ("auto", "legacy"):
            outcomes += await check_protocol(url, mode, expected)
    print("MCP smoke test passed: " + "; ".join(dict.fromkeys(outcomes)))
    print("Hostile Host and Origin headers were rejected.")


async def check_native() -> None:
    """Start a server on an unused loopback port and clean it up after testing."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        # With an API key, a cold directory download takes minutes; answer "loading" sooner.
        "OPENDART_MCP_DIRECTORY__WAIT": "3",
        **os.environ,
        "OPENDART_MCP_HTTP__HOST": "127.0.0.1",
        "OPENDART_MCP_HTTP__PORT": str(port),
    }
    async with await anyio.open_process(
        [sys.executable, "-m", "opendart_mcp.server"],
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
