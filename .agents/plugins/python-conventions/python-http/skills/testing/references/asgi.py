"""Optional in-process ASGI test, independent of other HTTP skill references.

Requires ``httpx2`` and the async/no-network fixtures from ``example.py``. Adapt
``service`` to an existing application. This small app has no lifespan resources;
for a real application, run its startup/shutdown lifecycle with an appropriate
lifespan manager because ``ASGITransport`` does not do that itself.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import httpx2
import pytest

pytestmark = pytest.mark.anyio

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


async def service(scope: Scope, receive: Receive, send: Send) -> None:
    """A minimal ASGI app standing in for a service of your own."""
    body = f"hello from {scope['path']}".encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


async def test_own_service_in_process() -> None:
    async with httpx2.AsyncClient(
        base_url="http://service", transport=httpx2.ASGITransport(app=service)
    ) as client:
        assert (await client.get("/status")).text == "hello from /status"
