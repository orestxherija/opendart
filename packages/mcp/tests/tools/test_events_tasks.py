"""get_corporate_events as a background task, in the foreground with progress, and deadlines."""

from __future__ import annotations

import anyio
import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp_tasks import call_tool_task  # importing fastmcp_tasks enables client tasks

from opendart_mcp.tools import events as events_tool
from packages.mcp.tests.events.data import convertible_bond, filing, merger, profile

ARGUMENTS = {"company": "005930"}


class NoTasksClient(Client[FastMCPTransport]):
    """A modern client without the tasks extension, like Claude hosts today."""

    _auto_internal_extensions = False


def routes(upstream):
    upstream.route("/company.json", upstream.ok(**profile()))

    def index(request):
        if request.url.params.get("pblntf_ty") != "B":
            return upstream.status("013")
        return upstream.rows(
            filing("20260915000123", "Decision on Issuance of Convertible Bonds"),
            filing("20260901000456", "Decision on Merger"),
        )

    upstream.route("/list.json", index)
    upstream.records("/cvbdIsDecsn.json", convertible_bond())
    upstream.records("/cmpMgDecsn.json", merger())


@pytest.mark.anyio
async def test_runs_as_a_background_task(client, upstream):
    routes(upstream)
    task = await call_tool_task(client, "get_corporate_events", ARGUMENTS)
    assert task.create_result.status == "working"
    result = await task.result()
    data = result.structured_content
    assert [event["kind"] for event in data["events"]] == ["convertible_bond", "merger"]
    assert "| Filed | Kind |" in result.content[0].text


@pytest.mark.anyio
async def test_foreground_calls_report_progress(server, upstream):
    routes(upstream)
    messages: list[str | None] = []

    async def on_progress(progress, total, message):
        messages.append(message)

    async with NoTasksClient(server, progress_handler=on_progress) as client:
        result = await client.call_tool("get_corporate_events", ARGUMENTS)
    assert result.structured_content["coverage"]["kinds_with_data"] == [
        "convertible_bond",
        "merger",
    ]
    assert messages[0] == "Searching SAMSUNG ELECTRONICS CO,.LTD's major-issue and offering filings"
    assert {"1/2", "2/2"} == {m.split()[0] for m in messages[1:]}


def stall(upstream):
    """Hold event report requests until the returned gate opens."""
    gate = anyio.Event()

    async def held(request):
        await gate.wait()
        return upstream.rows(convertible_bond())

    upstream.route("/company.json", upstream.ok(**profile()))
    upstream.route("/cvbdIsDecsn.json", held)
    return gate


@pytest.mark.anyio
async def test_foreground_deadline_asks_for_a_retry(server, upstream, monkeypatch):
    gate = stall(upstream)
    monkeypatch.setattr(events_tool, "FOREGROUND_DEADLINE", 0.2)
    async with NoTasksClient(server) as client:
        result = await client.call_tool(
            "get_corporate_events",
            {**ARGUMENTS, "categories": ["convertible_bond"]},
            raise_on_error=False,
        )
        assert result.is_error
        assert "still in progress. Retry in about a minute" in result.content[0].text
        gate.set()
        await anyio.sleep(0.05)
        retry = await client.call_tool(
            "get_corporate_events", {**ARGUMENTS, "categories": ["convertible_bond"]}
        )
    assert retry.structured_content["events"][0]["filing_number"] == "20260915000123"
    assert upstream.count("/cvbdIsDecsn.json") == 1  # the abandoned call filled the cache


@pytest.mark.anyio
async def test_background_deadline_ends_the_task_with_the_retry_message(
    client, upstream, monkeypatch
):
    gate = stall(upstream)
    monkeypatch.setattr(events_tool, "BACKGROUND_DEADLINE", 0.2)
    task = await call_tool_task(
        client,
        "get_corporate_events",
        {**ARGUMENTS, "categories": ["convertible_bond"]},
        raise_on_error=False,
    )
    result = await task.result()
    gate.set()
    await anyio.sleep(0.05)
    assert result.is_error
    assert "still in progress" in result.content[0].text
