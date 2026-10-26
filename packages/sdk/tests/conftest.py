"""Provide synthetic SDK settings and prevent real network access in tests."""

from __future__ import annotations

from collections.abc import Iterator

import httpx2
import pytest
from pydantic import SecretStr

from opendart import OpenDARTSettings, get_settings


@pytest.fixture
def anyio_backend() -> str:
    """Select the asyncio backend for asynchronous SDK tests.

    Returns:
        str: The anyio backend name asyncio.
    """
    return "asyncio"


@pytest.fixture
def settings() -> OpenDARTSettings:
    """Create valid upstream settings with a synthetic credential.

    Returns:
        OpenDARTSettings: Configuration suitable for mock-transport tests.
    """
    return OpenDARTSettings(api_key=SecretStr("synthetic-test-key".ljust(40, "x")))


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reject real HTTP requests and reset cached settings before and after each test.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture used to replace real HTTP transport entry
            points.

    Yields:
        None: Control while the test runs with network access disabled.
    """

    def refuse_sync(self: httpx2.HTTPTransport, request: httpx2.Request) -> httpx2.Response:
        """Fail a test that attempts a synchronous network request.

        Args:
            self (httpx2.HTTPTransport): Transport instance whose network access is blocked.
            request (httpx2.Request): Outgoing request rejected by this guard.

        Raises:
            AssertionError: Always, because real network access is forbidden in tests.
        """
        raise AssertionError("Test attempted a real HTTP request")

    async def refuse_async(
        self: httpx2.AsyncHTTPTransport,
        request: httpx2.Request,
    ) -> httpx2.Response:
        """Fail a test that attempts an asynchronous network request.

        Args:
            self (httpx2.AsyncHTTPTransport): Transport instance whose network access is blocked.
            request (httpx2.Request): Outgoing request rejected by this guard.

        Raises:
            AssertionError: Always, because real network access is forbidden in tests.
        """
        raise AssertionError("Test attempted a real HTTP request")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse_sync)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", refuse_async)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
