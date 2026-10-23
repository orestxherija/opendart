"""Background tasks end to end: task clients, legacy clients, and modern clients without tasks.

A dummy tool follows the shape of the task-enabled OpenDART tools: TASK_OPTIONAL, a Markdown
view, Reporter progress, and its own deadline through with_heartbeat.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import pytest
from fastmcp import Client, Context
from fastmcp.client.transports import FastMCPTransport
from fastmcp.dependencies import CurrentContext
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp_tasks import call_tool_task
from pydantic import BaseModel, Field

from opendart_mcp.app.annotations import READ_ONLY, TASK_OPTIONAL
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.metrics import count_upstream
from opendart_mcp.core.progress import with_heartbeat

FOREGROUND_DEADLINE = 0.3
BACKGROUND_DEADLINE = 5.0


class Steps(BaseModel):
    steps: int
    background: bool
    note: str | None = None


def render(result: Steps) -> str:
    return f"{result.steps} steps"


@tool(name="count_slowly", version="1.0.0", task=TASK_OPTIONAL, annotations=READ_ONLY)
@markdown_view(render)
async def count_slowly(
    *,
    steps: Annotated[int, Field(ge=1, le=20)] = 3,
    delay: float = 0.05,
    fail: bool = False,
    ctx: Context = CurrentContext(),
) -> Steps:
    """Count with progress, like a slow fan-out tool.

    Args:
        steps: Steps to take.
        delay: Seconds per step.
        fail: Fail with a domain error after counting.
        ctx: Request context, injected.
    """
    report = Reporter(ctx, total=steps)
    for index in range(steps):
        count_upstream()
        await asyncio.sleep(delay)
        await report(f"{index + 1}/{steps} step")
    if fail:
        message = "Ask for fewer steps."
        raise InvalidArgumentError(message)
    return Steps(steps=steps, background=ctx.is_background_task)


@tool(name="wait_for_download", version="1.0.0", task=TASK_OPTIONAL, annotations=READ_ONLY)
@markdown_view(render)
async def wait_for_download(*, seconds: float, ctx: Context = CurrentContext()) -> Steps:
    """Wait for slow shared work within the foreground or background deadline.

    Args:
        seconds: How long the work takes.
        ctx: Request context, injected.
    """
    deadline = BACKGROUND_DEADLINE if ctx.is_background_task else FOREGROUND_DEADLINE
    report = Reporter(ctx)
    await with_heartbeat(
        asyncio.sleep(seconds), report, label="Download", deadline=deadline, every=0.05
    )
    return Steps(steps=1, background=ctx.is_background_task)


class NoTasksClient(Client[FastMCPTransport]):
    """A 2026-07-28 client that does not declare the tasks extension, like Claude Code."""

    _auto_internal_extensions = False


@pytest.fixture
def server(wired):
    server = wired(tasks=True)
    server.add_tool(count_slowly)
    server.add_tool(wait_for_download)
    return server


@pytest.mark.anyio
async def test_task_clients_get_a_task_whose_status_follows_progress(server):
    async with Client(server) as client:
        task = await call_tool_task(client, "count_slowly", {"steps": 3, "delay": 0.1})
        assert task.create_result.status == "working"
        assert task.create_result.poll_interval_ms == 3000
        assert task.create_result.ttl_ms == 15 * 60 * 1000
        messages = set()
        async with asyncio.timeout(10):
            while (status := await task.status()).status == "working":
                messages.add(status.status_message)
                await asyncio.sleep(0.02)
        result = await task.result()
    assert status.status == "completed"
    assert messages - {None} <= {"1/3 step", "2/3 step", "3/3 step"}
    assert messages - {None}
    assert result.structured_content == {"steps": 3, "background": True}
    assert result.content[0].text == "3 steps"


@pytest.mark.anyio
async def test_domain_failures_in_tasks_reach_the_client(server):
    async with Client(server) as client:
        task = await call_tool_task(client, "count_slowly", {"steps": 1, "fail": True})
        with pytest.raises(ToolError, match=r"Ask for fewer steps\."):
            await task.result()


@pytest.mark.anyio
async def test_task_clients_can_call_transparently(server):
    async with Client(server) as client:
        result = await client.call_tool("count_slowly", {"steps": 2, "delay": 0.01})
    assert result.structured_content == {"steps": 2, "background": True}


@pytest.mark.anyio
async def test_legacy_clients_run_tools_in_the_foreground(server):
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("count_slowly", {"steps": 2, "delay": 0.01})
    assert result.structured_content == {"steps": 2, "background": False}


@pytest.mark.anyio
async def test_clients_without_tasks_get_progress_notifications(server):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total, message))

    async with NoTasksClient(server, progress_handler=on_progress) as client:
        result = await client.call_tool("count_slowly", {"steps": 3, "delay": 0.01})
    assert result.structured_content == {"steps": 3, "background": False}
    assert seen == [(1, 3, "1/3 step"), (2, 3, "2/3 step"), (3, 3, "3/3 step")]


@pytest.mark.anyio
async def test_foreground_calls_stop_at_their_deadline_while_tasks_wait_longer(server):
    async with NoTasksClient(server) as client:
        result = await client.call_tool("wait_for_download", {"seconds": 1.0}, raise_on_error=False)
    assert result.is_error
    assert result.content[0].text == (
        "Download is still in progress. Retry in about a minute; the result will be cached."
    )
    async with Client(server) as client:
        task = await call_tool_task(client, "wait_for_download", {"seconds": 0.5})
        finished = await task.result()
    assert finished.structured_content == {"steps": 1, "background": True}


@pytest.mark.anyio
async def test_invalid_arguments_fail_before_a_task_exists(server):
    async with Client(server) as client:
        result = await client.call_tool("count_slowly", {"steps": 0}, raise_on_error=False)
        with pytest.raises(ToolError, match="did not run as a task"):
            await call_tool_task(client, "count_slowly", {"steps": 0})
    assert result.is_error
    assert "greater than or equal to 1" in result.content[0].text


@pytest.mark.anyio
async def test_tasks_can_be_cancelled(server):
    async with Client(server) as client:
        task = await call_tool_task(client, "count_slowly", {"steps": 20, "delay": 1.0})
        await task.cancel()
        status = await task.wait(timeout=5)
    assert status.status == "cancelled"


@pytest.mark.anyio
async def test_each_background_run_is_counted_once(server, metrics):
    async with Client(server) as client:
        task = await call_tool_task(client, "count_slowly", {"steps": 2, "delay": 0.01})
        await task.result()
        await client.call_tool("count_slowly", {"steps": 2, "delay": 0.01})
    stats = metrics.components["tool:count_slowly"]
    assert (stats.calls, stats.upstream) == (2, 4)  # runs, not submissions


@pytest.mark.anyio
async def test_failures_in_background_runs_are_counted(server, metrics):
    async with Client(server) as client:
        task = await call_tool_task(client, "count_slowly", {"steps": 1, "fail": True})
        with pytest.raises(ToolError):
            await task.result()
    assert metrics.components["tool:count_slowly"].errors == {"InvalidArgumentError": 1}


@pytest.mark.anyio
async def test_background_work_is_attributed_to_its_tool(server, metrics):
    async with Client(server) as client:
        task = await call_tool_task(client, "count_slowly", {"steps": 2, "delay": 0.01})
        await task.result()
    assert metrics.components["tool:count_slowly"].upstream == 2


@pytest.mark.anyio
async def test_background_runs_work_without_usage_metrics(wired):
    server = wired(middleware=False, tasks=True)
    server.add_tool(count_slowly)
    async with Client(server) as client:
        task = await call_tool_task(client, "count_slowly", {"steps": 1, "delay": 0.01})
        result = await task.result()
    assert result.structured_content == {"steps": 1, "background": True}
