"""Minimal HTTP tests: a mock transport and a fake for application code.

This reference needs only ``httpx2``, ``pytest``, and ``anyio``. It imports no
client factory, auth scheme, retry helper, or billing adapter. Put the fixtures
and ``Upstream`` in ``tests/conftest.py``; adapt the tests to your existing code.
The repository loads this file as ``http_testing_reference`` so optional example
files can reuse the same fixtures and handler without duplicating them.

Register the socket-test escape hatch once in ``pyproject.toml``::

    [tool.pytest.ini_options]
    markers = ["network: opens real sockets, to 127.0.0.1 only"]

Load ``retries.py``, ``oauth2.py``, ``billing.py``, or ``asgi.py`` only when that
feature is under test. Each file lists its own prerequisites.
"""

from typing import Protocol

import httpx2
import pytest

pytestmark = pytest.mark.anyio

Outcome = int | httpx2.Response | type[httpx2.TransportError]


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio; select another backend only if the application supports it."""
    return "asyncio"


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that reaches a real transport, unless marked ``network``."""
    if request.node.get_closest_marker("network"):
        return

    def refuse_sync(
        self: httpx2.HTTPTransport, request: httpx2.Request
    ) -> httpx2.Response:
        raise RuntimeError(f"unit test reached the network: {request.url.host}")

    async def refuse_async(
        self: httpx2.AsyncHTTPTransport, request: httpx2.Request
    ) -> httpx2.Response:
        raise RuntimeError(f"unit test reached the network: {request.url.host}")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse_sync)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", refuse_async)


class Upstream:
    """Record requests and return scripted statuses, responses, or errors."""

    def __init__(self, *outcomes: Outcome) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, int):
            return httpx2.Response(outcome)
        if isinstance(outcome, httpx2.Response):
            return outcome
        raise outcome("scripted failure", request=request)


async def test_existing_client_uses_mock_transport() -> None:
    upstream = Upstream(httpx2.Response(200, json={"available": True}))
    async with httpx2.AsyncClient(
        base_url="https://service.example/v2/",
        transport=httpx2.MockTransport(upstream),
    ) as client:
        response = await client.get("status")
        response.raise_for_status()
    assert response.json() == {"available": True}
    assert upstream.requests[0].url.path == "/v2/status"


class BalanceReader(Protocol):
    """Only the capability application code needs from an existing adapter."""

    async def get_balance(self, account_id: str) -> int: ...


async def can_charge(reader: BalanceReader, account_id: str, amount: int) -> bool:
    """Illustrative application logic; normally imported from the application."""
    return await reader.get_balance(account_id) >= amount


class FakeBalances:
    """A test fake of the application's adapter contract, with no HTTP."""

    def __init__(self, balances: dict[str, int]) -> None:
        self._balances = balances

    async def get_balance(self, account_id: str) -> int:
        return self._balances.get(account_id, 0)


async def test_business_rule_with_a_fake() -> None:
    fake = FakeBalances({"acct_42": 100})
    assert await can_charge(fake, "acct_42", 99)
    assert not await can_charge(fake, "acct_missing", 1)
