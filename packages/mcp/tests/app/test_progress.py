"""Progress reporting: a monotonic Reporter, heartbeats, and deadline-bounded waits."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, Context
from fastmcp.dependencies import CurrentContext

from opendart_mcp.app.progress import Reporter
from opendart_mcp.core.errors import StillRunningError
from opendart_mcp.core.progress import HEARTBEAT_SECONDS, no_progress, with_heartbeat


class FakeContext:
    def __init__(self):
        self.reports = []

    async def report_progress(self, progress, total=None, message=None):
        self.reports.append((progress, total, message))


@pytest.mark.anyio
async def test_progress_strictly_increases():
    ctx = FakeContext()
    report = Reporter(ctx)
    for message in ("a", "b", "c"):
        await report(message)
    assert ctx.reports == [(1, None, "a"), (2, None, "b"), (3, None, "c")]


@pytest.mark.anyio
async def test_the_total_is_sent_only_while_it_still_holds():
    ctx = FakeContext()
    report = Reporter(ctx, total=2)
    for message in ("1/2", "2/2", "extra"):
        await report(message)
    assert ctx.reports == [(1, 2, "1/2"), (2, 2, "2/2"), (3, None, "extra")]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.anyio
async def test_reporter_reaches_clients_in_both_protocol_eras(wired, mode):
    server = wired()

    @server.tool
    async def count(ctx: Context = CurrentContext()) -> int:
        report = Reporter(ctx, total=2)
        for step in ("1/2 first", "2/2 second", "wrapping up"):
            await report(step)
        return 3

    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total, message))

    async with Client(server, mode=mode) as client:
        await client.call_tool("count", {}, progress_handler=on_progress)
    assert seen == [(1, 2, "1/2 first"), (2, 2, "2/2 second"), (3, None, "wrapping up")]


@pytest.mark.anyio
async def test_no_progress_discards_messages():
    assert await no_progress("ignored") is None
    assert HEARTBEAT_SECONDS == 5.0


@pytest.mark.anyio
async def test_quick_work_returns_without_heartbeats():
    messages = []

    async def record(message):
        messages.append(message)

    async def work():
        return 42

    assert await with_heartbeat(work(), record, label="Quick work", deadline=5) == 42
    assert messages == []


@pytest.mark.anyio
async def test_slow_work_sends_heartbeats_until_it_finishes():
    messages = []

    async def record(message):
        messages.append(message)

    async def work():
        await asyncio.sleep(0.25)
        return "done"

    result = await with_heartbeat(work(), record, label="Downloading", deadline=5, every=0.05)
    assert result == "done"
    assert len(messages) >= 2
    assert all(m.startswith("Downloading (") and m.endswith(" s elapsed)") for m in messages)


@pytest.mark.anyio
async def test_the_deadline_stops_waiting_but_not_the_work():
    finished = asyncio.Event()

    async def work():
        await asyncio.sleep(0.2)
        finished.set()
        return "late"

    task = asyncio.ensure_future(work())
    with pytest.raises(StillRunningError) as raised:
        await with_heartbeat(
            task, no_progress, label="Filing 20260814001234", deadline=0.05, every=0.01
        )
    assert str(raised.value) == (
        "Filing 20260814001234 is still in progress. Retry in about a minute; the result will be cached."
    )
    assert not task.cancelled()
    await asyncio.wait_for(finished.wait(), timeout=5)
    assert task.result() == "late"


@pytest.mark.anyio
async def test_an_expired_deadline_raises_before_waiting():
    async def work():
        return "never awaited"

    task = asyncio.ensure_future(work())
    with pytest.raises(StillRunningError):
        await with_heartbeat(task, no_progress, label="Work", deadline=0)
    assert await task == "never awaited"


@pytest.mark.anyio
async def test_failures_of_the_work_propagate():
    async def work():
        await asyncio.sleep(0.01)
        raise LookupError("upstream failed")

    with pytest.raises(LookupError, match="upstream failed"):
        await with_heartbeat(work(), no_progress, label="Work", deadline=5, every=0.005)
