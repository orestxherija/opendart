"""Bounded TTL caching and request coalescing."""

from __future__ import annotations

import asyncio

import anyio
import pytest

from opendart_mcp.core.cache import MISSING, SingleFlight, TTLCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_entries_expire_and_none_is_a_cacheable_value():
    clock = Clock()
    cache: TTLCache[str, object] = TTLCache(max_weight=10, clock=clock)
    cache.put("empty", None, ttl=5)
    cache.put("value", 1, ttl=10)
    assert cache.get("empty") is None
    clock.now = 6
    assert cache.get("empty") is MISSING
    assert cache.get("value") == 1
    stats = cache.stats()
    assert (stats.entries, stats.hits, stats.misses) == (1, 2, 1)


def test_weight_bound_evicts_least_recently_used():
    cache: TTLCache[str, int] = TTLCache(max_weight=5)
    cache.put("a", 1, ttl=60, weight=2)
    cache.put("b", 2, ttl=60, weight=2)
    assert cache.get("a") == 1  # a becomes most recently used
    cache.put("c", 3, ttl=60, weight=2)
    assert cache.get("b") is MISSING
    assert cache.get("a") == 1
    assert cache.stats().weight == 4


def test_oversized_and_zero_ttl_values_are_not_stored():
    cache: TTLCache[str, int] = TTLCache(max_weight=3)
    cache.put("big", 1, ttl=60, weight=4)
    cache.put("skip", 2, ttl=0)
    cache.put("again", 3, ttl=60)
    cache.put("again", 4, ttl=60, weight=2)
    assert cache.get("big") is MISSING
    assert cache.get("skip") is MISSING
    assert cache.get("again") == 4
    assert cache.stats().weight == 2
    cache.clear()
    assert cache.stats().entries == 0


@pytest.mark.anyio
async def test_single_flight_shares_one_run():
    flight: SingleFlight[str, int] = SingleFlight()
    runs = 0
    gate = anyio.Event()

    async def work() -> int:
        nonlocal runs
        runs += 1
        await gate.wait()
        return 42

    results: list[int] = []

    async def caller() -> None:
        results.append(await flight.run("k", work))

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(caller)
        await anyio.wait_all_tasks_blocked()
        assert flight.in_flight == 1
        gate.set()
    assert results == [42, 42, 42]
    assert runs == 1
    assert flight.in_flight == 0


@pytest.mark.anyio
async def test_cancelled_caller_does_not_cancel_shared_work():
    flight: SingleFlight[str, str] = SingleFlight()
    gate = anyio.Event()

    async def work() -> str:
        await gate.wait()
        return "done"

    with anyio.move_on_after(0.01):
        await flight.run("k", work)
    assert flight.in_flight == 1
    gate.set()
    assert await flight.run("k", work) == "done"


@pytest.mark.anyio
async def test_failures_reach_every_caller_and_are_not_retained():
    flight: SingleFlight[str, int] = SingleFlight()

    async def fail() -> int:
        await asyncio.sleep(0)
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await flight.run("k", fail)
    assert flight.in_flight == 0


@pytest.mark.anyio
async def test_abandoned_failures_are_retrieved():
    flight: SingleFlight[str, int] = SingleFlight()
    loop = asyncio.get_running_loop()
    unhandled: list[object] = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

    async def fail() -> int:
        await asyncio.sleep(0.01)
        raise ValueError("late")

    with anyio.move_on_after(0.001):
        await flight.run("k", fail)
    await asyncio.sleep(0.05)
    assert flight.in_flight == 0
    assert unhandled == []
