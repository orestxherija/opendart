"""Optional retry fixtures and a retry test, independent of any API adapter.

Requires ``app.http_retries`` from the retries skill and ``Upstream`` plus the
async/no-network fixtures from ``example.py``. In this repository that file is
loaded as ``http_testing_reference``; in a project import your own test support.
Put ``waits`` in ``tests/conftest.py`` only for tests that need retry control.
"""

import httpx2
import pytest
from http_testing_reference import Upstream

import app.http_retries as http_retries
from app.http_retries import RetrySettings, send_with_retries

pytestmark = pytest.mark.anyio


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record retry waits instead of sleeping; jitter returns its upper bound."""
    recorded: list[float] = []

    async def record(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(http_retries, "sleep", record)
    monkeypatch.setattr(http_retries, "uniform", lambda low, high: high)
    return recorded


async def test_retry_waits_without_sleeping(waits: list[float]) -> None:
    upstream = Upstream(503, 503, 200)
    async with httpx2.AsyncClient(
        base_url="https://service.example/", transport=httpx2.MockTransport(upstream)
    ) as client:
        response = await send_with_retries(
            lambda: client.get("status"), RetrySettings()
        )
    assert response.status_code == 200
    assert waits == [0.5, 1.0]
