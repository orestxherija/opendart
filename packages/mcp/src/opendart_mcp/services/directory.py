"""Background loading, on-disk caching, and daily refresh of the company directory.

OpenDART publishes the directory as one ZIP that can take minutes to download, so the
server never blocks startup on it. A cached copy on disk makes restarts immediate, a stale
copy is served while a fresh one downloads, and codes keep working while names cannot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import anyio
import anyio.to_thread

from opendart import OpenDARTError
from opendart_analysis.domain.directory import Directory, DirectoryError, parse_directory
from opendart_mcp.core.errors import (
    API_KEY_MISSING,
    ConfigurationError,
    DirectoryUnavailableError,
    ServerError,
)
from opendart_mcp.core.gateway import translate

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from opendart_mcp.core.progress import Progress
    from opendart_mcp.settings import DirectorySettings

logger = logging.getLogger(__name__)

type Status = Literal["loading", "ready", "failed", "disabled"]

ARCHIVE_NAME = "corpcode.zip"
_RETRY_DELAYS = (60.0, 300.0, 900.0, 3600.0)
_PROGRESS_INTERVAL = 5.0


@dataclass(frozen=True, slots=True)
class DirectoryInfo:
    """Directory state for the status resource.

    Attributes:
        status (Status): Loading state.
        companies (int): Number of companies in the loaded directory.
        listed (int): Number of listed companies.
        loaded_at (datetime | None): When the loaded archive was downloaded.
        source (str | None): "disk" or "download".
        error (str | None): Last load failure, if any.
    """

    status: Status
    companies: int
    listed: int
    loaded_at: datetime | None
    source: str | None
    error: str | None


class DirectoryService:
    """Own the company directory: load, cache, refresh, and wait for readiness."""

    def __init__(
        self,
        fetch: Callable[[], Awaitable[bytes]] | None,
        settings: DirectorySettings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Configure the service; call run() in a task group to start loading.

        Args:
            fetch (Callable[[], Awaitable[bytes]] | None): Downloads the archive; None when
                no API key is configured, so only a cached archive can be used.
            settings (DirectorySettings): Cache location, ages, and wait limits.
            clock (Callable[[], datetime]): Aware clock for archive ages.
        """
        self._fetch = fetch
        self._settings = settings
        self._clock = clock
        self._directory: Directory | None = None
        self._source: str | None = None
        self._error: str | None = None
        self._started = clock()
        # Set once the first load attempt finishes, successfully or not.
        self._settled = anyio.Event()

    @property
    def directory(self) -> Directory | None:
        """The loaded directory, or None before the first successful load.

        Returns:
            Directory | None: Current index.
        """
        return self._directory

    def info(self) -> DirectoryInfo:
        """Describe the current state for the status resource.

        Returns:
            DirectoryInfo: Snapshot of the service state.
        """
        directory = self._directory
        return DirectoryInfo(
            status=self._status(),
            companies=len(directory) if directory else 0,
            listed=directory.listed_count if directory else 0,
            loaded_at=directory.loaded_at if directory else None,
            source=self._source,
            error=self._error,
        )

    async def wait(self, seconds: float, progress: Progress | None = None) -> Directory:
        """Return the directory, waiting up to a timeout while it loads.

        Args:
            seconds (float): Maximum seconds to wait.
            progress (Progress | None): Called every few seconds while waiting.

        Returns:
            Directory: The loaded directory.

        Raises:
            ConfigurationError: No API key and no cached archive.
            DirectoryUnavailableError: Still loading after the wait, or loading failed.
        """
        if self._directory is None and not self._settled.is_set():
            with anyio.move_on_after(seconds):
                await self._wait_ready(progress)
        if self._directory is not None:
            return self._directory
        raise self._unavailable()

    async def run(self) -> None:
        """Load the directory, then keep it fresh until cancelled.

        Failed refreshes keep serving the previous directory and back off for an hour, so a
        persistent upstream problem does not spend the API key's daily quota.
        """
        await self._load_initial()
        while self._fetch is not None:
            await anyio.sleep(self._next_refresh())
            if not await self._refresh():
                await anyio.sleep(_RETRY_DELAYS[-1])

    async def _wait_ready(self, progress: Progress | None) -> None:
        """Wait for the first load to settle, reporting progress periodically.

        Args:
            progress (Progress | None): Progress callback.
        """
        while not self._settled.is_set():
            with anyio.move_on_after(_PROGRESS_INTERVAL):
                await self._settled.wait()
            if progress is not None and not self._settled.is_set():
                elapsed = int((self._clock() - self._started).total_seconds())
                await progress(f"Loading the OpenDART company directory ({elapsed} s elapsed)")

    def _status(self) -> Status:
        """Classify the current state.

        Returns:
            Status: Loading state.
        """
        if self._directory is not None:
            return "ready"
        if self._settled.is_set():
            return "failed" if self._fetch is not None else "disabled"
        return "loading"

    def _unavailable(self) -> ServerError:
        """Explain why no directory is available.

        Returns:
            ServerError: Configuration or availability error for the caller.
        """
        if self._fetch is None:
            return ConfigurationError(API_KEY_MISSING)
        hint = "Meanwhile, pass an 8-digit DART corp code, which works without the directory."
        if self._error is not None:
            message = f"The company directory could not be loaded ({self._error}); the server is retrying in the background. {hint}"
            return DirectoryUnavailableError(message)
        elapsed = int((self._clock() - self._started).total_seconds())
        message = f"The company directory is still loading ({elapsed} s so far; OpenDART can take several minutes). Retry shortly. {hint}"
        return DirectoryUnavailableError(message)

    async def _load_initial(self) -> None:
        """Load from disk when possible, otherwise download, retrying with backoff."""
        cached = await self._read_cache()
        if cached is not None and self._age(cached[1]) < self._max_age():
            return
        for delay in (*_RETRY_DELAYS, None):
            if await self._refresh() or self._fetch is None or delay is None:
                return
            await anyio.sleep(delay)

    async def _refresh(self) -> bool:
        """Download, cache, and install a fresh directory.

        Returns:
            bool: Whether a fresh directory was installed.
        """
        if self._fetch is None:
            self._settled.set()
            return False
        try:
            with anyio.fail_after(self._settings.deadline):
                archive = await self._fetch()
            await self._install(archive, self._clock(), "download", cache=True)
        except (OpenDARTError, ServerError, DirectoryError, TimeoutError) as error:
            return self._failed(_reason(error))
        except Exception as error:
            # A bug must not leave the directory "loading" forever with nothing logged.
            logger.exception("Company directory load failed unexpectedly")
            return self._failed(f"unexpected {type(error).__name__}")
        return True

    def _failed(self, reason: str) -> bool:
        """Record a failed load attempt.

        Args:
            reason (str): Safe description of the failure.

        Returns:
            bool: Always False, for ``_refresh`` to return.
        """
        self._error = reason
        logger.warning("Company directory download failed: %s", reason)
        self._settled.set()
        return False

    async def _install(
        self, archive: bytes, downloaded: datetime, source: str, *, cache: bool = False
    ) -> None:
        """Parse and index an archive in a worker thread, then make it current.

        A valid downloaded archive is written to the disk cache before it is activated.

        Args:
            archive (bytes): Directory ZIP.
            downloaded (datetime): When the archive was downloaded.
            source (str): "disk" or "download".
            cache (bool): Whether to store the archive in the disk cache.
        """
        directory = await anyio.to_thread.run_sync(_build, archive, downloaded)
        if cache:
            await self._write_cache(archive)
        self._directory = directory
        self._source, self._error = source, None
        self._settled.set()
        logger.info("Company directory loaded from %s: %d companies", source, len(directory))

    def _cache_path(self) -> Path | None:
        """Locate the cached archive.

        Returns:
            Path | None: Archive path, or None when disk caching is disabled.
        """
        directory = self._settings.cache_dir
        return None if directory is None else directory / ARCHIVE_NAME

    async def _read_cache(self) -> tuple[bytes, datetime] | None:
        """Install the cached archive if one exists and parses.

        Returns:
            tuple[bytes, datetime] | None: Archive bytes and modification time, or None.
        """
        path = self._cache_path()
        try:
            if path is None or not path.is_file():
                return None
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            archive = await anyio.to_thread.run_sync(path.read_bytes)
            await self._install(archive, modified, "disk")
        except (OSError, DirectoryError) as error:
            logger.warning("Ignoring unreadable directory cache: %s", error)
            return None
        except Exception:
            logger.exception("Ignoring the directory cache after an unexpected error")
            return None
        return archive, modified

    async def _write_cache(self, archive: bytes) -> None:
        """Store the archive atomically; failures only disable caching.

        Args:
            archive (bytes): Directory ZIP to store.
        """
        path = self._cache_path()
        if path is None:
            return
        try:
            await anyio.to_thread.run_sync(_atomic_write, path, archive)
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

    def _max_age(self) -> float:
        """Configured refresh age in seconds.

        Returns:
            float: Maximum archive age.
        """
        return self._settings.max_age_hours * 3600

    def _next_refresh(self) -> float:
        """Seconds until the current archive reaches its maximum age.

        Returns:
            float: Delay before the next refresh, at least one minute.
        """
        directory = self._directory
        if directory is None:
            return _RETRY_DELAYS[-1]
        return max(self._max_age() - self._age(directory.loaded_at), 60.0)


def _reason(error: Exception) -> str:
    """Describe an expected load failure safely.

    Args:
        error (Exception): SDK, server, archive, or timeout failure.

    Returns:
        str: Message for the status resource and tool errors.
    """
    if isinstance(error, OpenDARTError):
        return str(translate(error))
    return str(error) or type(error).__name__


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
