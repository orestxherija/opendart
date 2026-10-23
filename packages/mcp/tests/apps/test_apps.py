"""MCP Apps over the protocol: tool links, ui:// resources, and self-contained pages."""

from __future__ import annotations

import re

import pytest
from mcp.types import TextResourceContents

from opendart_mcp.apps.links import CALENDAR_URI, FINANCIALS_URI, PEERS_URI

pytestmark = pytest.mark.anyio

APPS = {
    "get_financials": FINANCIALS_URI,
    "compare_companies": PEERS_URI,
    "get_corporate_action_calendar": CALENDAR_URI,
}
UI_MIME = "text/html;profile=mcp-app"
PAGE_UI = {"csp": {}, "prefersBorder": True}
# Messages of the MCP Apps protocol (2026-01-26) that every page sends or handles.
PROTOCOL = (
    '"2026-01-26"',
    '"ui/initialize"',
    '"ui/notifications/initialized"',
    '"ui/notifications/tool-input"',
    '"ui/notifications/tool-result"',
    '"ui/notifications/tool-cancelled"',
    '"ui/notifications/host-context-changed"',
    '"ui/notifications/size-changed"',
    '"ui/update-model-context"',
    '"ui/resource-teardown"',
    "new ResizeObserver(",
    "window.parent.postMessage(",
    "event.source !== window.parent",
)
EXTERNAL = re.compile(r"<script[^>]*\bsrc\s*=|<link\b|https?://|@import|\burl\(")
UNSAFE = re.compile(
    r"\b(innerHTML|outerHTML|insertAdjacentHTML|eval|fetch|XMLHttpRequest|WebSocket)\b|document\.write"
)


async def test_linked_tools_name_their_app_and_no_other_tool_does(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    for name, uri in APPS.items():
        meta = tools[name].meta
        assert meta["ui"] == {"resourceUri": uri}
        assert meta["ui/resourceUri"] == uri
        assert re.fullmatch(r"\d+\.\d+\.\d+", meta["fastmcp"]["version"])
        assert tools[name].output_schema is not None
    linked = {name for name, tool in tools.items() if "ui" in (tool.meta or {})}
    assert linked == set(APPS)


async def test_app_resources_are_framed_html_that_declares_no_origins(client):
    resources = {str(resource.uri): resource for resource in await client.list_resources()}
    apps = {uri: resource for uri, resource in resources.items() if uri.startswith("ui://")}
    assert sorted(apps) == sorted(APPS.values())
    for resource in apps.values():
        assert resource.mime_type == UI_MIME
        assert resource.meta["ui"] == PAGE_UI
        assert resource.meta["fastmcp"]["tags"] == ["app"]
        assert resource.meta["fastmcp"]["version"] == "1.0.0"
        assert resource.title.endswith(" app")
        assert resource.description.startswith("Interactive view of ")
        assert resource.name.endswith("_app")


@pytest.mark.parametrize("uri", list(APPS.values()))
async def test_each_page_is_small_self_contained_and_speaks_the_protocol(client, uri):
    (item,) = await client.read_resource(uri)
    assert isinstance(item, TextResourceContents)
    assert item.mime_type == UI_MIME
    assert item.meta == {"ui": PAGE_UI}
    page = item.text
    assert len(page.encode()) < 64 * 1024
    assert page.startswith("<!doctype html>\n")
    assert page.endswith("</html>\n")
    assert (page.count("<script"), page.count("<style"), page.count("</script>")) == (1, 1, 1)
    assert EXTERNAL.search(page) is None, "pages load nothing from any origin"
    assert UNSAFE.search(page) is None, "pages never parse data as HTML or fetch"
    assert "textContent" in page
    for marker in PROTOCOL:
        assert marker in page, marker


async def test_pages_are_fixed_documents(client):
    first = [(await client.read_resource(uri))[0].text for uri in APPS.values()]
    again = [(await client.read_resource(uri))[0].text for uri in APPS.values()]
    assert first == again
    assert len(set(first)) == len(APPS)
