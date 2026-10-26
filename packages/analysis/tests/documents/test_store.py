"""DocumentStore: single flight, background completion, failures, eviction, progress, close."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from opendart_analysis.documents import (
    DocumentStore,
    DownloadPendingError,
    MalformedArchiveError,
    ParsedFiling,
    StoreClosedError,
)

pytestmark = pytest.mark.anyio


@dataclass
class Stub:
    """Stands in for a ParsedFiling; only rendered_chars matters to the store."""

    number: str
    rendered_chars: int = 10


class Upstream:
    """A fetch function whose downloads finish when released."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.gate = asyncio.Event()
        self.failures: list[BaseException] = []

    async def fetch(self, number: str) -> bytes:
        self.calls.append(number)
        await self.gate.wait()
        if self.failures:
            raise self.failures.pop(0)
        return number.encode()


def stub_parse(sizes: dict[str, int] | None = None):
    def parse(number: str, archive: bytes) -> Stub:
        assert archive == number.encode()
        return Stub(number, (sizes or {}).get(number, 10))

    return parse


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_concurrent_callers_share_one_download():
    upstream = Upstream()
    async with DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse()) as store:
        waiters = [asyncio.create_task(store.get("A", wait_s=5)) for _ in range(3)]
        await settle()
        assert store.stats().in_flight == 1
        upstream.gate.set()
        results = await asyncio.gather(*waiters)
        assert upstream.calls == ["A"]
        assert results[0] is results[1] is results[2]
        assert await store.get("A", wait_s=0) is results[0]
        stats = store.stats()
        assert (stats.entries, stats.misses, stats.hits, stats.in_flight) == (1, 1, 1, 0)
        assert stats.rendered_chars == 10


async def test_slow_downloads_continue_after_the_caller_gives_up():
    upstream = Upstream()
    async with DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse()) as store:
        with pytest.raises(DownloadPendingError) as caught:
            await store.get("A", wait_s=0.02)
        assert caught.value.filing_number == "A"
        assert caught.value.waited_s >= 0.02
        with pytest.raises(DownloadPendingError):
            await store.get("A", wait_s=0)
        upstream.gate.set()
        joined = await store.get("A", wait_s=5)
        await settle()
        assert store.stats().entries == 1
        assert await store.get("A", wait_s=0) is joined
        assert upstream.calls == ["A"]


async def test_cancelled_callers_do_not_cancel_the_download():
    upstream = Upstream()
    async with DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse()) as store:
        caller = asyncio.create_task(store.get("A", wait_s=5))
        await settle()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        upstream.gate.set()
        result = await store.get("A", wait_s=5)
        assert result.number == "A"
        assert upstream.calls == ["A"]


async def test_failures_reach_every_waiter_and_are_not_cached():
    upstream = Upstream()
    upstream.failures.append(RuntimeError("upstream down"))
    async with DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse()) as store:
        waiters = [asyncio.create_task(store.get("A", wait_s=5)) for _ in range(2)]
        await settle()
        upstream.gate.set()
        results = await asyncio.gather(*waiters, return_exceptions=True)
        assert all(isinstance(r, RuntimeError) for r in results)
        await settle()
        assert store.stats().failures == 1
        assert (await store.get("A", wait_s=5)).number == "A"
        assert upstream.calls == ["A", "A"]


async def test_parse_errors_propagate():
    upstream = Upstream()
    upstream.gate.set()

    def broken(number: str, archive: bytes) -> ParsedFiling:
        raise MalformedArchiveError("bad archive")

    async with DocumentStore(upstream.fetch, max_rendered_chars=100, parse=broken) as store:
        with pytest.raises(MalformedArchiveError, match="bad archive"):
            await store.get("A", wait_s=5)


async def test_least_recently_used_filings_are_evicted():
    upstream = Upstream()
    upstream.gate.set()
    sizes = {"A": 40, "B": 40, "C": 40, "BIG": 500}
    async with DocumentStore(
        upstream.fetch, max_rendered_chars=100, parse=stub_parse(sizes)
    ) as store:
        first = await store.get("A", wait_s=5)
        await store.get("B", wait_s=5)
        assert await store.get("A", wait_s=0) is first
        await store.get("C", wait_s=5)
        await settle()
        assert store.stats().entries == 2
        assert (await store.get("A", wait_s=0)) is first
        with pytest.raises(DownloadPendingError):
            await store.get("B", wait_s=0)
        # B reloads in the background; let it finish so BIG is the most recent entry.
        await store.get("B", wait_s=5)
        await store.get("BIG", wait_s=5)
        await settle()
        assert (store.stats().entries, store.stats().rendered_chars) == (1, 500)


async def test_growing_filings_are_rechecked_on_every_hit():
    upstream = Upstream()
    upstream.gate.set()
    async with DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse()) as store:
        first = await store.get("A", wait_s=5)
        second = await store.get("B", wait_s=5)
        await settle()
        first.rendered_chars = 95
        assert await store.get("B", wait_s=0) is second
        assert store.stats().entries == 1


async def test_progress_messages_while_waiting():
    upstream = Upstream()
    messages: list[str] = []
    reported = asyncio.Event()

    async def progress(message: str) -> None:
        messages.append(message)
        reported.set()

    store = DocumentStore(
        upstream.fetch, max_rendered_chars=100, parse=stub_parse(), progress_every_s=0.005
    )
    waiter = asyncio.create_task(store.get("A", wait_s=5, on_progress=progress))
    await asyncio.wait_for(reported.wait(), timeout=5)
    upstream.gate.set()
    assert (await waiter).number == "A"
    assert messages[0].startswith("Downloading and parsing filing A:")
    await store.aclose()


async def test_closing_cancels_unfinished_downloads():
    upstream = Upstream()
    store = DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse())
    waiter = asyncio.create_task(store.get("A", wait_s=5))
    await settle()
    await store.aclose()
    with pytest.raises(StoreClosedError, match="closed while"):
        await waiter
    with pytest.raises(StoreClosedError, match="is closed"):
        await store.get("A", wait_s=1)
    stats = store.stats()
    assert (stats.entries, stats.in_flight) == (0, 0)


async def test_real_parsing_runs_in_a_worker_thread(periodic_archive):
    async def fetch(number: str) -> bytes:
        return periodic_archive

    async with DocumentStore(fetch, max_rendered_chars=10_000_000) as store:
        parsed = await store.get("20260515003117", wait_s=30)
        assert isinstance(parsed, ParsedFiling)
        assert parsed.form_code == "11013"
        assert store.stats().rendered_chars == parsed.rendered_chars


async def test_stalled_downloads_time_out_and_are_retried():
    upstream = Upstream()
    store = DocumentStore(
        upstream.fetch, max_rendered_chars=100, parse=stub_parse(), fetch_timeout_s=0.01
    )
    with pytest.raises(TimeoutError):
        await store.get("A", wait_s=5)
    await settle()
    assert (store.stats().failures, store.stats().in_flight) == (1, 0)
    upstream.gate.set()
    assert (await store.get("A", wait_s=5)).number == "A"
    assert upstream.calls == ["A", "A"]
    await store.aclose()


async def test_waiting_without_a_budget_lasts_until_the_task_finishes():
    upstream = Upstream()
    messages: list[str] = []

    async def progress(message: str) -> None:
        messages.append(message)

    store = DocumentStore(
        upstream.fetch, max_rendered_chars=100, parse=stub_parse(), progress_every_s=0.005
    )
    waiter = asyncio.create_task(store.get("A", on_progress=progress))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    assert messages
    upstream.gate.set()
    assert (await waiter).number == "A"
    await store.aclose()


async def test_closing_ends_an_unbounded_wait():
    upstream = Upstream()
    store = DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse())
    waiter = asyncio.create_task(store.get("A"))
    await settle()
    await store.aclose()
    with pytest.raises(StoreClosedError, match="closed while"):
        await waiter


async def test_parallel_fetches_are_bounded_when_asked():
    upstream = Upstream()
    store = DocumentStore(
        upstream.fetch, max_rendered_chars=100, parse=stub_parse(), max_parallel_fetches=2
    )
    waiters = [asyncio.create_task(store.get(number)) for number in "ABCDE"]
    await settle()
    assert upstream.calls == ["A", "B"]
    assert store.stats().in_flight == 5
    upstream.gate.set()
    assert [(await waiter).number for waiter in waiters] == list("ABCDE")
    assert sorted(upstream.calls) == list("ABCDE")
    await store.aclose()


async def test_queued_fetches_do_not_spend_the_download_deadline():
    upstream = Upstream()
    upstream.gate.set()
    first = asyncio.Event()

    async def fetch(number: str) -> bytes:
        if number == "A":
            await first.wait()
        return await upstream.fetch(number)

    store = DocumentStore(
        fetch,
        max_rendered_chars=100,
        parse=stub_parse(),
        max_parallel_fetches=1,
        fetch_timeout_s=0.05,
    )
    slow = asyncio.create_task(store.get("A"))
    queued = asyncio.create_task(store.get("B"))
    await asyncio.sleep(0.03)
    first.set()
    assert (await slow).number == "A"
    assert (await queued).number == "B"
    await store.aclose()


async def test_downloads_are_unbounded_by_default():
    upstream = Upstream()
    store = DocumentStore(upstream.fetch, max_rendered_chars=100, parse=stub_parse())
    waiters = [asyncio.create_task(store.get(number)) for number in "ABCDE"]
    await settle()
    assert upstream.calls == list("ABCDE")
    upstream.gate.set()
    await asyncio.gather(*waiters)
    await store.aclose()


@pytest.mark.parametrize("bound", [0, -1])
def test_parallel_fetches_need_at_least_one_slot(bound):
    with pytest.raises(ValueError, match="at least 1"):
        DocumentStore(Upstream().fetch, max_rendered_chars=100, max_parallel_fetches=bound)
