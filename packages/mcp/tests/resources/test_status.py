"""The server status resource."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.metrics import ComponentStats
from opendart_mcp.server import create_server
from opendart_mcp.services.status import _component, _upstream

STATUS = "opendart://server/status"


async def status(client):
    (content,) = await client.read_resource(STATUS)
    assert content.mime_type == "application/json"
    return json.loads(content.text)


@pytest.mark.anyio
async def test_status_is_listed_for_user_and_assistant(client):
    resources = {str(r.uri): r for r in await client.list_resources()}
    resource = resources[STATUS]
    assert resource.mime_type == "application/json"
    assert resource.meta is not None
    assert resource.meta["fastmcp"]["version"] == "1.0.0"
    assert resource.annotations is not None
    assert resource.annotations.audience == ["user", "assistant"]


@pytest.mark.anyio
async def test_status_reports_usage_caches_and_settings(client, upstream, sdk_settings):
    await client.call_tool("find_company", {"query": "Samsung Electronics"})
    await client.call_tool("find_company", {"query": "Samsung Electronics"})
    data = await status(client)
    assert data["as_of"] == "2026-10-22T10:00:00+09:00"
    assert data["started"] == data["as_of"]
    assert data["uptime_seconds"] == 0
    assert data["version"]
    assert data["api_key_configured"] is True
    directory = data["directory"]
    assert (directory["status"], directory["companies"], directory["source"]) == (
        "ready",
        len(upstream.companies),
        "download",
    )
    assert directory["loaded_at"] == "2026-10-22T10:00:00+09:00"
    usage = data["upstream"]
    assert (usage["day"], usage["today"], usage["total"]) == ("2026-10-22", 1, 1)
    assert usage["by_operation"] == {"corporation_codes": 1}
    assert {"entries", "hits", "misses", "max_weight"} <= set(data["response_cache"])
    assert data["documents"]["entries"] == 0
    tool = data["components"]["tool:find_company"]
    assert (tool["calls"], tool["errors"], tool["upstream"]) == (2, 0, 0)
    settings = data["settings"]
    assert settings["service_tools_enabled"] is False
    assert settings["upstream_concurrency"] == 5
    assert settings["cache_ttl_seconds"]["filing_searches"] == 900
    assert "directory_cache_dir" not in settings
    secret = sdk_settings.api_key.get_secret_value()
    assert secret not in json.dumps(data)


@pytest.mark.anyio
async def test_status_counts_failures_by_type(client):
    await client.call_tool("get_company_profile", {"company": "Samsung"}, raise_on_error=False)
    await status(client)
    data = await status(client)
    failed = data["components"]["tool:get_company_profile"]
    assert failed["errors"] == 1
    assert list(failed["error_types"].values()) == [1]
    assert data["components"]["resource:opendart://server/status"]["calls"] == 1


@pytest.mark.anyio
async def test_status_without_an_api_key(mcp_settings, upstream):
    async with Client(create_server(mcp_settings, transport=upstream.transport)) as client:
        data = await status(client)
    assert data["api_key_configured"] is False
    assert "upstream" not in data
    assert "documents" not in data
    assert data["directory"]["companies"] == 0
    assert "loaded_at" not in data["directory"]
    assert upstream.count() == 0


def test_component_usage_handles_a_component_without_calls():
    usage = _component(ComponentStats())
    assert (usage.calls, usage.avg_ms, usage.errors) == (0, 0.0, 0)


def test_upstream_usage_before_any_request(sdk):
    gateway = Gateway(sdk, cache=TTLCache(max_weight=100), concurrency=1)
    usage = _upstream(gateway)
    assert usage is not None
    assert usage.day is None
    assert usage.today == 0
