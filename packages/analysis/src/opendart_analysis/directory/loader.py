"""Background loading, on-disk caching, and refresh of the corporation-code directory.

OpenDART publishes the directory as one ZIP that can take minutes to download, so a
long-running application should not block on it. ``DirectoryLoader`` loads it in the
background: a cached copy on disk makes restarts immediate, a stale copy is served while a
fresh one downloads, failed downloads are retried with backoff, and the archive is downloaded
again once it reaches its maximum age.

Lifecycle: create the loader anywhere; nothing runs until the caller calls ``start()`` (or
enters ``async with``), or awaits ``run()`` in a task it owns. Use it from one asyncio event
loop and ``await loader.aclose()`` (or leave ``async with``) on shutdown. The caller owns
``fetch`` and whatever client it uses; closing the loader never closes that client.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Self

from opendart_analysis.directory.errors import DirectoryNotReadyError, LoadFailure
from opendart_analysis.domain.corpcode import parse_directory
from opendart_analysis.domain.directory import Directory
from opendart_analysis.domain.records import DirectoryError
from opendart_analysis.errors import NotConfiguredError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from types import TracebackType

logger = logging.getLogger(__name__)

type FetchArchive = Callable[[], Awaitable[bytes]]
"""Download the corporation-code archive (ZIP bytes)."""

type DescribeError = Callable[[Exception], str]
"""Describe an exception raised by the fetch callback, safely, for status and errors."""

type Progress = Callable[[str], Awaitable[None]]
"""Report a progress message while a caller waits."""

type LoaderStatus = Literal["loading", "ready", "failed", "disabled"]
type ArchiveSource = Literal["disk", "download"]

RETRY_DELAYS_S = (60.0, 300.0, 900.0, 3600.0)
"""Default waits between failed initial attempts; the last also follows a failed refresh."""

MIN_REFRESH_S = 60.0
"""Shortest wait before a scheduled refresh."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LoaderConfig:
    """Cache location, refresh schedule, and limits for a ``DirectoryLoader``.

    Attributes:
        cache_path (Path | None): File holding the cached archive; None disables disk caching.
            The file is the archive exactly as downloaded, and its modification time records
            when it was downloaded. Defaults to None.
        max_age_s (float): Archive age, in seconds, after which it is downloaded again.
            Defaults to 24 hours.
        fetch_timeout_s (float | None): Overall deadline for one download; None disables it.
            Defaults to 900.
        retry_delays_s (tuple[float, ...]): Seconds between failed initial attempts; the last
            delay also follows every failed refresh. Defaults to 1, 5, 15, and 60 minutes.
        progress_every_s (float): Seconds between progress messages while a caller waits.
            Defaults to 5.
    """

    cache_path: Path | None = None
    max_age_s: float = 86_400.0
    fetch_timeout_s: float | None = 900.0
    retry_delays_s: tuple[float, ...] = RETRY_DELAYS_S
    progress_every_s: float = 5.0

    def __post_init__(self) -> None:
        """Reject values that would make the schedule meaningless.

        Raises:
            ValueError: A non-positive age, timeout, or progress interval, or missing or
                negative retry delays.
        """
        if not self.max_age_s > 0 or not self.progress_every_s > 0:
            msg = "max_age_s and progress_every_s must be positive"
            raise ValueError(msg)
        if self.fetch_timeout_s is not None and not self.fetch_timeout_s > 0:
            msg = "fetch_timeout_s must be positive or None"
            raise ValueError(msg)
        if not self.retry_delays_s or min(self.retry_delays_s) < 0:
            msg = "retry_delays_s needs at least one non-negative delay"
            raise ValueError(msg)


def _message(error: Exception) -> str:
    """Describe a failure by its message, or its type when it has none.

    Args:
        error (Exception): Failure to describe.

    Returns:
        str: Description.
    """
    return str(error) or type(error).__name__


class DirectoryLoader:
    """Load, cache, and refresh the directory; wait for it while it loads.

    The loader requires an asyncio event loop: it uses ``asyncio`` tasks, timeouts, and
    worker threads, so it does not run under Trio, even through AnyIO.
    """

    def __init__(
        self,
        fetch: FetchArchive | None,
        config: LoaderConfig | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        describe_error: DescribeError | None = None,
    ) -> None:
        """Configure the loader; no work starts until :meth:`start` or :meth:`run`.

        Args:
            fetch (FetchArchive | None): Downloads the archive, for example
                ``client.disclosures.corporation_codes``. None means only a cached archive can
                be used, and the loader never downloads.
            config (LoaderConfig | None): Cache location, schedule, and limits. Defaults to
                ``LoaderConfig()``, which caches nothing on disk.
            clock (Callable[[], datetime]): Aware clock for archive ages. Defaults to UTC now.
            describe_error (DescribeError | None): Describes exceptions raised by ``fetch``;
                it must not raise. Defaults to the exception's message, or its type name.
        """
        self.config = config or LoaderConfig()
        self._fetch = fetch
        self._clock = clock
        self._describe = describe_error or _message
        self._directory: Directory | None = None
        self._source: ArchiveSource | None = None
        self._failure: LoadFailure | None = None
        self._started = clock()
        # Settled once the first load attempt finishes, successfully or not.
        self._settled = False
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._attempts = 0
        self._last_ok = False
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    async def __aenter__(self) -> Self:
        """Start background loading for an ``async with`` block.

        Returns:
            Self: This loader.
        """
        self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the loader, cancelling background work.

        Args:
            exc_type (type[BaseException] | None): Exception type from the block, or None.
            exc (BaseException | None): Exception from the block, or None.
            traceback (TracebackType | None): Its traceback, or None.
        """
        await self.aclose()

    @property
    def directory(self) -> Directory | None:
        """The current directory, or None before the first successful load."""
        return self._directory

    @property
    def source(self) -> ArchiveSource | None:
        """Where the current directory came from: ``disk`` or ``download``."""
        return self._source

    @property
    def failure(self) -> LoadFailure | None:
        """The last failed attempt, cleared by the next successful load."""
        return self._failure

    @property
    def status(self) -> LoaderStatus:
        """``ready``, else ``loading`` until the first attempt settles, then ``failed``.

        Without ``fetch`` and a usable cache, the settled status is ``disabled``.
        """
        if self._directory is not None:
            return "ready"
        if self._settled:
            return "failed" if self._fetch is not None else "disabled"
        return "loading"

    def start(self) -> None:
        """Run :meth:`run` in a task the loader owns, until :meth:`aclose`; idempotent.

        Raises:
            RuntimeError: The loader is closed.
        """
        if self._closed:
            msg = "The directory loader is closed"
            raise RuntimeError(msg)
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="opendart-directory-loader")

    async def run(self) -> None:
        """Load the directory, then keep it fresh until cancelled.

        Uses a fresh cache file when there is one; otherwise installs any readable cache
        and downloads, retrying after each of ``retry_delays_s``. Then downloads again
        whenever the archive reaches ``max_age_s``. A failed refresh keeps the previous
        directory and waits the last retry delay, so a persistent upstream problem does not
        spend a request quota. Without ``fetch``, returns after reading the cache.

        Raises:
            RuntimeError: The loader is closed or already running.
        """
        if self._closed or self._running:
            state = "closed" if self._closed else "already running"
            msg = f"The directory loader is {state}"
            raise RuntimeError(msg)
        self._running = True
        self._started = self._clock()
        try:
            await self._load_initial()
            while self._fetch is not None:
                await asyncio.sleep(self._next_refresh())
                if not await self.refresh():
                    await asyncio.sleep(self.config.retry_delays_s[-1])
        finally:
            self._running = False

    async def refresh(self) -> bool:
        """Download, cache, and install a fresh directory now.

        A call made while another refresh is in progress waits for it and returns its
        outcome instead of downloading again. Failures are recorded in :attr:`failure`.

        Returns:
            bool: Whether a fresh directory was installed.
        """
        attempts = self._attempts
        async with self._lock:
            if self._attempts != attempts:
                return self._last_ok
            self._last_ok = await self._attempt()
            self._attempts += 1
            return self._last_ok

    async def wait(
        self, timeout_s: float | None = None, *, on_progress: Progress | None = None
    ) -> Directory:
        """Return the directory, waiting up to ``timeout_s`` for the first attempt to settle.

        Args:
            timeout_s (float | None): Longest wait in seconds; None waits until the first
                attempt settles or the loader closes. Defaults to None.
            on_progress (Progress | None): Awaited with a message every ``progress_every_s``
                seconds while waiting.

        Returns:
            Directory: The current directory.

        Raises:
            NotConfiguredError: No directory is loaded and there is no ``fetch``
                (``dependency`` is ``fetch``).
            DirectoryNotReadyError: Still loading after the wait, or every attempt failed.
        """
        if self._directory is None and not self._settled and not self._closed:
            scope = asyncio.timeout(timeout_s)
            try:
                async with scope:
                    await self._wait_settled(on_progress)
            except TimeoutError:
                if not scope.expired():
                    raise
        if self._directory is not None:
            return self._directory
        if self._fetch is None:
            msg = "No archive download was supplied and no cached company directory is usable."
            raise NotConfiguredError(msg, dependency="fetch")
        raise DirectoryNotReadyError(elapsed_s=self._age(self._started), failure=self._failure)

    async def aclose(self) -> None:
        """Cancel the task :meth:`start` created and wake waiting callers.

        The current directory stays readable. A :meth:`run` awaited by the caller stops when
        the caller cancels it.
        """
        self._closed = True
        self._wake.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _wait_settled(self, on_progress: Progress | None) -> None:
        """Wait for the first attempt to settle, reporting progress periodically.

        Args:
            on_progress (Progress | None): Progress callback.
        """
        while not (self._settled or self._closed):
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self.config.progress_every_s):
                    await self._wake.wait()
            if on_progress is not None and not (self._settled or self._closed):
                elapsed = int(self._age(self._started))
                await on_progress(f"Loading the OpenDART company directory ({elapsed} s elapsed)")

    async def _load_initial(self) -> None:
        """Load from disk when fresh enough, otherwise download, retrying with backoff."""
        modified = await self._read_cache()
        if modified is not None and self._age(modified) < self.config.max_age_s:
            return
        for delay in (*self.config.retry_delays_s, None):
            if await self.refresh() or self._fetch is None or delay is None:
                return
            await asyncio.sleep(delay)

    async def _attempt(self) -> bool:
        """Download, cache, and install a fresh directory once, recording any failure.

        Returns:
            bool: Whether a fresh directory was installed.
        """
        if self._fetch is None:
            self._settle()
            return False
        archive: bytes | None = None
        try:
            async with asyncio.timeout(self.config.fetch_timeout_s):
                archive = await self._fetch()
            await self._install(archive, self._clock(), "download", cache=True)
        except Exception as error:  # noqa: BLE001 - every failure is recorded and reported
            reason = self._reason(error, fetched=archive is not None)
            self._failure = LoadFailure(reason, error)
            logger.warning("Company directory download failed: %s", reason)
            self._settle()
            return False
        return True

    def _reason(self, error: Exception, *, fetched: bool) -> str:
        """Describe a failed attempt.

        Args:
            error (Exception): What the fetch callback, the parser, or the loader raised.
            fetched (bool): Whether the fetch had returned, so the error came later.

        Returns:
            str: ``describe_error`` for a fetch failure, the message of an unusable archive,
                or ``unexpected <type>`` for anything else, which is also logged.
        """
        if not fetched:
            return self._describe(error)
        if isinstance(error, DirectoryError):
            return _message(error)
        # A bug must not leave the directory "loading" forever with nothing logged.
        logger.error("Company directory load failed unexpectedly", exc_info=error)
        return f"unexpected {type(error).__name__}"

    def _settle(self) -> None:
        """Mark the first attempt as finished and wake waiting callers."""
        self._settled = True
        self._wake.set()

    async def _install(
        self, archive: bytes, downloaded: datetime, source: ArchiveSource, *, cache: bool = False
    ) -> None:
        """Parse and index an archive in a worker thread, then make it current.

        A valid downloaded archive is written to the disk cache before it is activated.

        Args:
            archive (bytes): Directory ZIP.
            downloaded (datetime): When the archive was downloaded.
            source (ArchiveSource): ``disk`` or ``download``.
            cache (bool): Whether to store the archive in the disk cache.
        """
        directory = await asyncio.to_thread(_build, archive, downloaded)
        if cache:
            await self._write_cache(archive)
        self._directory = directory
        self._source, self._failure = source, None
        self._settle()
        logger.info("Company directory loaded from %s: %d companies", source, len(directory))

    async def _read_cache(self) -> datetime | None:
        """Install the cached archive if one exists and parses.

        Returns:
            datetime | None: The archive's modification time, or None when none was installed.
        """
        path = self.config.cache_path
        try:
            if path is None or not path.is_file():
                return None
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            archive = await asyncio.to_thread(path.read_bytes)
            await self._install(archive, modified, "disk")
        except (OSError, DirectoryError) as error:
            logger.warning("Ignoring unreadable directory cache: %s", error)
            return None
        except Exception:
            logger.exception("Ignoring the directory cache after an unexpected error")
            return None
        return modified

    async def _write_cache(self, archive: bytes) -> None:
        """Store the archive atomically; failures only disable caching.

        Args:
            archive (bytes): Directory ZIP to store.
        """
        path = self.config.cache_path
        if path is None:
            return
        try:
            await asyncio.to_thread(_atomic_write, path, archive)
        except OSError as error:
            logger.warning("Cannot cache the company directory at %s: %s", path, error)

    def _age(self, moment: datetime) -> float:
        """Seconds elapsed since a moment.

        Args:
            moment (datetime): Aware timestamp.

        Returns:
            float: Elapsed seconds.
        """
        return (self._clock() - moment).total_seconds()

    def _next_refresh(self) -> float:
        """Seconds until the current archive reaches its maximum age.

        Returns:
            float: Delay before the next refresh, at least ``MIN_REFRESH_S``; the last retry
                delay when nothing is loaded.
        """
        directory = self._directory
        if directory is None:
            return self.config.retry_delays_s[-1]
        return max(self.config.max_age_s - self._age(directory.loaded_at), MIN_REFRESH_S)


def _build(archive: bytes, loaded_at: datetime) -> Directory:
    """Parse and index a directory archive; CPU-bound, run in a worker thread.

    Args:
        archive (bytes): Directory ZIP.
        loaded_at (datetime): When the archive was downloaded.

    Returns:
        Directory: Search index.
    """
    return Directory.build(parse_directory(archive), loaded_at=loaded_at)


def _atomic_write(path: Path, data: bytes) -> None:
    """Write a file through a temporary sibling and an atomic rename.

    Args:
        path (Path): Destination file.
        data (bytes): Content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
