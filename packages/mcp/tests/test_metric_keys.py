"""Usage metrics stay bounded whatever names and URIs clients send."""

from __future__ import annotations

import pytest

from opendart_mcp.app.middleware import UNKNOWN_TOOL, resource_key
from opendart_mcp.app.state import STATE_KEY
from opendart_mcp.core.metrics import MAX_KEYS, OVERFLOW_KEY, Metrics


def test_distinct_keys_are_capped():
    metrics = Metrics()
    for index in range(MAX_KEYS + 5):
        metrics.record(f"resource:x{index}", elapsed_ms=1.0, upstream=0)
    assert len(metrics.components) == MAX_KEYS + 1
    assert metrics.components[OVERFLOW_KEY].calls == 5


@pytest.mark.parametrize(
    ("uri", "key"),
    [
        ("opendart://company/00126380", "resource:opendart://company/{id}"),
        (
            "opendart://filing/20260814001234/sections/D-0-3-2-0",
            "resource:opendart://filing/{id}/sections/{section}",
        ),
        (
            "opendart://company/00126380/filings?since=30d",
            "resource:opendart://company/{id}/filings",
        ),
    ],
)
def test_resource_keys_follow_templates(uri, key):
    assert resource_key(uri) == key


@pytest.mark.anyio
async def test_unknown_tools_share_one_key(server, client):
    await client.call_tool("no_such_tool_1", {}, raise_on_error=False)
    await client.call_tool("no_such_tool_2", {}, raise_on_error=False)
    state = server._lifespan_result[STATE_KEY]
    keys = set(state.metrics.components)
    assert UNKNOWN_TOOL in keys
    assert not any(key.startswith("tool:no_such") for key in keys)
