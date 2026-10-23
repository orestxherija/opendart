"""Bounded in-memory caching and request coalescing for upstream responses.

The container has a small memory budget, so the cache is bounded by a caller-supplied
weight (for example, the number of upstream records) rather than by entry count alone.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable


class _Missing:
    """Sentinel type distinguishing a cache miss from a cached None."""

    __slots__ = ()


MISSING: Final = _Missing()


@dataclass(slots=True)
class _Entry[V]:
    """One cached value with its expiry time and weight."""

    value: V
    expires: float
    weight: int


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Point-in-time cache counters for the status resource.

    Attributes:
        entries (int): Live and not-yet-evicted entries.
        weight (int): Total weight of stored entries.
        max_weight (int): Configured weight bound.
        hits (int): Lookups served from the cache.
        misses (int): Lookups that found nothing or an expired entry.
    """

    entries: int
    weight: int
    max_weight: int
    hits: int
    misses: int


class TTLCache[K: Hashable, V]:
    """Least-recently-used cache with per-entry expiry and a total weight bound."""

    def __init__(self, *, max_weight: int, clock: Callable[[], float] = time.monotonic) -> None:
        """Create an empty cache.

        Args:
            max_weight (int): Upper bound on the summed weight of stored entries.
            clock (Callable[[], float]): Monotonic clock in seconds; injectable for tests.
        """
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._max_weight = max_weight
        self._weight = 0
        self._clock = clock
        self._hits = 0
        self._misses = 0

    def get(self, key: K) -> V | _Missing:
        """Return a live value and mark it recently used.

        Args:
            key (K): Cache key.

        Returns:
            V | _Missing: The cached value, which may itself be None, or MISSING.
        """
        entry = self._entries.get(key)
        if entry is None or entry.expires <= self._clock():
            if entry is not None:
                self._remove(key)
            self._misses += 1
            return MISSING
        self._entries.move_to_end(key)
        self._hits += 1
        return entry.value

    def put(self, key: K, value: V, *, ttl: float, weight: int = 1) -> None:
        """Store a value, evicting least-recently-used entries beyond the weight bound.

        Values heavier than the whole bound are not stored.

        Args:
            key (K): Cache key.
            value (V): Value to store; None is a valid cached value.
            ttl (float): Seconds until expiry; non-positive values store nothing.
            weight (int): Relative size of the value, at least 1.
        """
        weight = max(weight, 1)
        if ttl <= 0 or weight > self._max_weight:
            return
        if key in self._entries:
            self._remove(key)
        self._entries[key] = _Entry(value, self._clock() + ttl, weight)
        self._weight += weight
        while self._weight > self._max_weight:
            self._remove(next(iter(self._entries)))

    def clear(self) -> None:
        """Drop every entry while keeping the hit and miss counters."""
        self._entries.clear()
        self._weight = 0

    def stats(self) -> CacheStats:
        """Report current size and hit counters.

        Returns:
            CacheStats: Counters for the status resource.
        """
        return CacheStats(
            entries=len(self._entries),
            weight=self._weight,
            max_weight=self._max_weight,
            hits=self._hits,
            misses=self._misses,
        )

    def _remove(self, key: K) -> None:
        """Remove one entry and release its weight.

        Args:
            key (K): Key of an existing entry.
        """
        self._weight -= self._entries.pop(key).weight


class SingleFlight[K: Hashable, V]:
    """Coalesce concurrent calls for the same key into one shared task.

    Cancelling a caller never cancels the shared task: the work continues for the other
    callers, and a later caller for the same key joins it. Callers wait with
    ``asyncio.wait``, which leaves the task running when the waiter is cancelled, rather than
    ``asyncio.shield``, which reports failures of abandoned work as unhandled. The server
    runs on asyncio, so this uses asyncio tasks directly.
    """

    def __init__(self) -> None:
        """Create a coalescer with no work in flight."""
        self._tasks: dict[K, asyncio.Task[V]] = {}

    @property
    def in_flight(self) -> int:
        """Number of keys with running work.

        Returns:
            int: Count of distinct in-flight keys.
        """
        return len(self._tasks)

    async def run(self, key: K, work: Callable[[], Awaitable[V]]) -> V:
        """Run work for a key, or join the run already in flight for it.

        Args:
            key (K): Identity of the work.
            work (Callable[[], Awaitable[V]]): Factory for the coroutine to run once.

        Returns:
            V: The shared result.
        """
        task = self._tasks.get(key)
        if task is None:
            task = asyncio.ensure_future(work())
            self._tasks[key] = task
            task.add_done_callback(lambda done: self._finish(key, done))
        await asyncio.wait((task,))
        return task.result()

    def _finish(self, key: K, task: asyncio.Task[V]) -> None:
        """Forget a finished task and mark its exception as retrieved.

        Args:
            key (K): Key the task ran for.
            task (asyncio.Task[V]): The finished task.
        """
        if self._tasks.get(key) is task:
            del self._tasks[key]
        if not task.cancelled():
            # Every caller may have been cancelled; avoid "exception never retrieved" logs.
            task.exception()
