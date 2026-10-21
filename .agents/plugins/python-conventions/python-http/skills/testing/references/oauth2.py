"""Optional OAuth token-expiry test with a controllable clock.

Requires ``app.http_oauth2`` from auth's ``oauth2.py`` and the async/no-network
fixtures in testing's ``example.py``. No client factory or retry helper is used.
Put ``clock`` in ``tests/conftest.py`` only when testing this token-cache module.
"""

import httpx2
import pytest
from pydantic import SecretStr

import app.http_oauth2 as http_oauth2
from app.http_oauth2 import ClientCredentialsAuth, ClientCredentialsSettings

pytestmark = pytest.mark.anyio


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """A fake monotonic clock for token expiry; advance it instead of sleeping."""
    now = [1000.0]
    monkeypatch.setattr(http_oauth2, "monotonic", lambda: now[0])
    return now


async def test_token_is_refreshed_after_expiry(clock: list[float]) -> None:
    issued: list[str] = []

    def upstream(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "idp.example":
            issued.append(f"t{len(issued) + 1}")
            return httpx2.Response(
                200, json={"access_token": issued[-1], "expires_in": 60}
            )
        return httpx2.Response(200)

    auth = ClientCredentialsAuth(
        ClientCredentialsSettings(
            token_url="https://idp.example/token",
            client_id="app",
            client_secret=SecretStr("secret"),
        )
    )
    async with httpx2.AsyncClient(
        base_url="https://service.example/",
        auth=auth,
        transport=httpx2.MockTransport(upstream),
    ) as client:
        await client.get("status")
        clock[0] += 61
        await client.get("status")
    assert issued == ["t1", "t2"]
