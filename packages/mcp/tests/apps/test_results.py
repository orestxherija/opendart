"""Linked tools answer the same whether or not the host renders apps.

A host that renders apps gets exactly the text and structured content every other host gets,
and that structured content carries the fields the app pages read.
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.apps import UI_EXTENSION_ID, UI_MIME_TYPE
from fastmcp.client.transports import FastMCPTransport
from mcp.client.extension import advertise

from packages.mcp.tests.events.data import HYNIX, buyback, filing, profile
from packages.mcp.tests.tools.financials_data import HYNIX as HYNIX_CODE, by_params, summary_rows

pytestmark = pytest.mark.anyio


class HostClient(Client[FastMCPTransport]):
    """A client without the tasks extension, like today's Claude hosts."""

    _auto_internal_extensions = False


def ui_extension():
    return [advertise(UI_EXTENSION_ID, {"mimeTypes": [UI_MIME_TYPE]})]


HOSTS = {
    "text only": dict,
    "apps": lambda: {"extensions": ui_extension()},
    "apps on the legacy protocol": lambda: {"mode": "legacy", "extensions": ui_extension()},
}


async def answers(server, name, arguments):
    results = {}
    for host, options in HOSTS.items():
        async with HostClient(server, **options()) as client:
            results[host] = await client.call_tool(name, arguments)
    return results


def same_everywhere(results):
    """Check that every host got the same result, and return its structured content."""
    expected = results["text only"]
    for host, result in results.items():
        assert not result.is_error, host
        assert [block.model_dump() for block in result.content] == [
            block.model_dump() for block in expected.content
        ], host
        assert result.structured_content == expected.structured_content, host
        assert "ui" not in (result.meta or {}), host
    assert expected.content[0].text.startswith("**"), "the text view is Markdown, not JSON"
    return expected.structured_content


async def test_financials_do_not_depend_on_app_support(server, upstream):
    table = {("2025", "11011"): upstream.rows(*summary_rows())}
    upstream.route("/fnlttSinglAcnt.json", by_params(table, "bsns_year", "reprt_code"))
    arguments = {"company": "005930", "fiscal_year": 2025, "period": "FY"}
    data = same_everywhere(await answers(server, "get_financials", arguments))
    read_by_app = {"company", "as_of", "view", "basis_used", "unit", "currency", "periods", "rows"}
    assert read_by_app <= set(data)
    assert {"label", "end_date", "fiscal_year", "period"} <= set(data["periods"][0])
    assert {"account", "values"} <= set(data["rows"][0])
    assert all(len(row["values"]) == len(data["periods"]) for row in data["rows"])


async def test_peer_tables_do_not_depend_on_app_support(server, upstream):
    upstream.route("/company.json", upstream.ok(corp_cls="Y", acc_mt="12"))
    rows = summary_rows() + summary_rows(corp=HYNIX_CODE, scale=2)
    table = {("2025", "11011"): upstream.rows(*rows)}
    upstream.route("/fnlttMultiAcnt.json", by_params(table, "bsns_year", "reprt_code"))
    data = same_everywhere(
        await answers(server, "compare_companies", {"companies": ["005930", "000660"]})
    )
    read_by_app = {"company_count", "fiscal_year", "period", "basis", "unit", "columns", "rows"}
    assert read_by_app <= set(data)
    assert set(data["columns"][0]) == {"key", "label", "unit"}
    assert {column["unit"] for column in data["columns"]} == {"krw", "pct"}
    assert all(len(row["values"]) == len(data["columns"]) for row in data["rows"])
    assert data["missing"] == []


async def test_calendars_do_not_depend_on_app_support(server, upstream):
    decision = filing("20261019000305", "Decision on Acquisition of Treasury Stock", HYNIX)

    def index(request):
        if request.url.params.get("pblntf_ty") != "B":
            return upstream.status("013")
        return upstream.rows(decision)

    upstream.route("/company.json", upstream.ok(**profile(HYNIX)))
    upstream.route("/list.json", index)
    upstream.route("/tsstkAqDecsn.json", upstream.rows(buyback()))
    data = same_everywhere(
        await answers(server, "get_corporate_action_calendar", {"companies": ["000660"]})
    )
    assert {"start", "end", "horizon_days", "companies", "items", "as_of", "notes"} <= set(data)
    (item,) = data["items"]
    keys = {"date", "company", "action", "source_kind", "filing_number", "dart_url", "details"}
    assert set(item) == keys
    assert (item["date"], item["action"]) == ("2027-01-20", "buyback_end")
    assert item["dart_url"].endswith("rcpNo=20261019000305")
    assert item["details"]["event"]
