"""Single-flight download, parse, and LRU cache for filing documents.

Filings are immutable (corrections arrive under new filing numbers), so cached results never
expire; the cache is bounded by the rendered characters it holds. Each filing is fetched and
parsed by one plain asyncio task owned by the store, so concurrent callers share it and it
outlives a caller that times out or is cancelled: its result is cached when it finishes.
Callers wait with ``asyncio.wait``, which never cancels the shared task.

Lifecycle: create the store anywhere, use it from one asyncio event loop, and
``await store.aclose()`` (or leave ``async with store:``) on shutdown to cancel unfinished work.
No task group is held open, so a host such as the MCP server may start and stop the store in
different tasks.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from functools import partial
from typing import TYPE_CHECKING, Self

import anyio
import anyio.to_thread

from opendart_analysis.documents.errors import DownloadPendingError, StoreClosedError
from opendart_analysis.documents.filing import parse_filing
from opendart_analysis.documents.models import DocumentStoreStats

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from opendart_analysis.documents.filing import ParsedFiling

type Fetch = Callable[[str], Awaitable[bytes]]
"""Download a filing archive (ZIP bytes) by filing number."""

type Parse = Callable[[str, bytes], ParsedFiling]
"""Parse a filing archive; runs in a worker thread."""

type Progress = Callable[[str], Awaitable[None]]
"""Report a progress message while a caller waits."""


class DocumentStore:
    """Fetch, parse, and cache filings, one shared task per filing number.

    The store requires an asyncio event loop: it creates plain ``asyncio`` tasks, so it does
    not run under Trio, even through AnyIO. The caller owns ``fetch`` and whatever client it
    uses; closing the store cancels its own tasks but never closes that client.

    Attributes:
        max_rendered_chars (int): Cache budget in rendered characters.
    """

    def __init__(
        self,
        fetch: Fetch,
        *,
        max_rendered_chars: int,
        parse: Parse = parse_filing,
        progress_every_s: float = 5.0,
        max_parallel_parses: int = 2,
        fetch_timeout_s: float | None = 120.0,
    ) -> None:
        """Configure the store; no work starts until :meth:`get` is called.

        Args:
            fetch (Fetch): Downloads archive bytes, for example
                ``lambda number: client.disclosures.document(filing_number=number)``.
            max_rendered_chars (int): Cache budget; the most recent filing is always kept.
            parse (Parse): Archive parser, run in a worker thread. Defaults to
                :func:`parse_filing`.
            progress_every_s (float): Seconds between progress messages. Defaults to 5.
            max_parallel_parses (int): Worker threads parsing at once, bounding memory.
                Defaults to 2.
            fetch_timeout_s (float | None): Overall deadline for one download, so a stalled
                transfer fails (and is retried by the next caller) instead of staying in
                flight. None disables it. Defaults to 120.
        """
        self.max_rendered_chars = max_rendered_chars
        self._fetch = fetch
        self._parse = parse
        self._every = progress_every_s
        self._parallel = max_parallel_parses
        self._fetch_timeout = fetch_timeout_s
        self._limiter: anyio.CapacityLimiter | None = None
        self._cache: OrderedDict[str, ParsedFiling] = OrderedDict()
        self._tasks: dict[str, asyncio.Task[ParsedFiling]] = {}
        self._counts = {"hits": 0, "misses": 0, "failures": 0}
        self._closed = False

    async def __aenter__(self) -> Self:
        """Return the store for use in an ``async with`` block.

        Returns:
            Self: This store.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the store, cancelling unfinished downloads.

        Args:
            exc_type (type[BaseException] | None): Exception type from the block, or None.
            exc (BaseException | None): Exception from the block, or None.
            traceback (TracebackType | None): Its traceback, or None.
        """
        await self.aclose()

    async def get(
        self,
        filing_number: str,
        *,
        wait_s: float | None = None,
        on_progress: Progress | None = None,
    ) -> ParsedFiling:
        """Return a parsed filing, downloading and parsing it once if needed.

        Args:
            filing_number (str): 14-digit filing number.
            wait_s (float | None): Longest time to wait for a download or parse in progress.
                None waits until the shared task finishes; ``fetch_timeout_s`` still bounds
                the download. Defaults to None.
            on_progress (Progress | None): Awaited with a message every few seconds while
                waiting.

        Returns:
            ParsedFiling: The parsed filing.

        Raises:
            DownloadPendingError: The work is still running after a finite ``wait_s``; it
                continues and its result is cached.
            StoreClosedError: The store is closed, or closed while waiting.
            Exception: Whatever the fetch or parse raised; failures are not cached.
        """
        if self._closed:
            msg = "The document store is closed"
            raise StoreClosedError(msg)
        cached = self._cache.get(filing_number)
        if cached is not None:
            self._cache.move_to_end(filing_number)
            self._counts["hits"] += 1
            self._evict()
            return cached
        task = self._tasks.get(filing_number)
        if task is None:
            self._counts["misses"] += 1
            task = asyncio.create_task(self._load(filing_number), name=f"filing {filing_number}")
            self._tasks[filing_number] = task
            task.add_done_callback(partial(self._settle, filing_number))
        return await self._wait(filing_number, task, wait_s=wait_s, on_progress=on_progress)

    def stats(self) -> DocumentStoreStats:
        """Report cache statistics, for example for a status resource.

        Returns:
            DocumentStoreStats: Entries, rendered characters, hits, misses, and work in flight.
        """
        return DocumentStoreStats(
            entries=len(self._cache),
            rendered_chars=self._rendered_chars(),
            max_rendered_chars=self.max_rendered_chars,
            hits=self._counts["hits"],
            misses=self._counts["misses"],
            in_flight=len(self._tasks),
            failures=self._counts["failures"],
        )

    async def aclose(self) -> None:
        """Cancel unfinished downloads, wait for them to stop, and drop the cache.

        A parse already running in a worker thread finishes before its task stops.
        """
        self._closed = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._cache.clear()

    async def _load(self, filing_number: str) -> ParsedFiling:
        """Download and parse one filing.

        Args:
            filing_number (str): 14-digit filing number.

        Returns:
            ParsedFiling: The parsed filing.

        Raises:
            TimeoutError: The download exceeded ``fetch_timeout_s``.
        """
        async with asyncio.timeout(self._fetch_timeout):
            archive = await self._fetch(filing_number)
        if self._limiter is None:
            self._limiter = anyio.CapacityLimiter(self._parallel)
        return await anyio.to_thread.run_sync(
            self._parse, filing_number, archive, limiter=self._limiter
        )

    def _settle(self, filing_number: str, task: asyncio.Task[ParsedFiling]) -> None:
        """Cache a finished task's result, or count its failure.

        Args:
            filing_number (str): Filing the task loaded.
            task (asyncio.Task[ParsedFiling]): The finished task.
        """
        if self._tasks.get(filing_number) is task:
            del self._tasks[filing_number]
        if task.cancelled() or self._closed:
            return
        if task.exception() is not None:
            self._counts["failures"] += 1
            return
        self._cache[filing_number] = task.result()
        self._cache.move_to_end(filing_number)
        self._evict()

    async def _wait(
        self,
        filing_number: str,
        task: asyncio.Task[ParsedFiling],
        *,
        wait_s: float | None,
        on_progress: Progress | None,
    ) -> ParsedFiling:
        """Wait for a shared task without cancelling it, reporting progress.

        Args:
            filing_number (str): Filing being loaded.
            task (asyncio.Task[ParsedFiling]): The shared task.
            wait_s (float | None): Longest wait in seconds; None waits for completion.
            on_progress (Progress | None): Progress callback.

        Returns:
            ParsedFiling: The task's result.

        Raises:
            DownloadPendingError: The task is still running after a finite ``wait_s``.
            StoreClosedError: The task was cancelled because the store closed.
        """
        loop = asyncio.get_running_loop()
        started = loop.time()
        while not task.done():
            timeout = self._every
            if wait_s is not None:
                remaining = started + wait_s - loop.time()
                if remaining <= 0:
                    raise DownloadPendingError(filing_number, loop.time() - started)
                timeout = min(timeout, remaining)
            await asyncio.wait({task}, timeout=timeout)
            if not task.done() and on_progress is not None:
                elapsed = loop.time() - started
                await on_progress(
                    f"Downloading and parsing filing {filing_number}: {elapsed:.0f} s elapsed"
                )
        if task.cancelled():
            msg = "The document store closed while the filing was loading"
            raise StoreClosedError(msg)
        return task.result()

    def _evict(self) -> None:
        """Drop least recently used filings until the cache fits its budget."""
        total = self._rendered_chars()
        while total > self.max_rendered_chars and len(self._cache) > 1:
            _, evicted = self._cache.popitem(last=False)
            total -= evicted.rendered_chars

    def _rendered_chars(self) -> int:
        """Count rendered characters across cached filings.

        Returns:
            int: Total rendered characters.
        """
        return sum(parsed.rendered_chars for parsed in self._cache.values())
