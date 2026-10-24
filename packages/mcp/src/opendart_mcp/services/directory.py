"""Background loading, on-disk caching, and daily refresh of the company directory.

OpenDART publishes the directory as one ZIP that can take minutes to download, so the
server never blocks startup on it. A cached copy on disk makes restarts immediate, a stale
copy is served while a fresh one downloads, and codes keep working while names cannot.

``opendart_analysis.directory.DirectoryLoader`` does the loading. This adapter configures it
from ``DirectorySettings``, describes SDK failures as the gateway does, and explains an
unavailable directory with the server's errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from opendart import OpenDARTError
from opendart_analysis.directory import (
    DirectoryError,
    DirectoryLoader,
    DirectoryNotReadyError,
    LoaderConfig,
)
from opendart_analysis.errors import NotConfiguredError
from opendart_mcp.core.errors import (
    API_KEY_MISSING,
    ConfigurationError,
    DirectoryUnavailableError,
    ServerError,
)
from opendart_mcp.core.gateway import translate

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from opendart_analysis.directory import Directory
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.settings import DirectorySettings

logger = logging.getLogger(__name__)

type Status = Literal["loading", "ready", "failed", "disabled"]

ARCHIVE_NAME = "corpcode.zip"
_RETRY_DELAYS = (60.0, 300.0, 900.0, 3600.0)
_PROGRESS_INTERVAL = 5.0
_HINT = "Meanwhile, pass an 8-digit DART corp code, which works without the directory."


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


def loader_config(settings: DirectorySettings) -> LoaderConfig:
    """Translate the directory settings into the analysis loader's configuration.

    Args:
        settings (DirectorySettings): Cache location, ages, and download deadline.

    Returns:
        LoaderConfig: Cache file ``<cache_dir>/corpcode.zip`` (None without a cache
            directory), refresh age, download deadline, retry delays, and progress interval.
    """
    cache_dir = settings.cache_dir
    return LoaderConfig(
        cache_path=None if cache_dir is None else cache_dir / ARCHIVE_NAME,
        max_age_s=settings.max_age_hours * 3600,
        fetch_timeout_s=settings.deadline,
        retry_delays_s=_RETRY_DELAYS,
        progress_every_s=_PROGRESS_INTERVAL,
    )


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
        self._loader = DirectoryLoader(
            fetch, loader_config(settings), clock=clock, describe_error=_reason
        )

    @property
    def directory(self) -> Directory | None:
        """The loaded directory, or None before the first successful load.

        Returns:
            Directory | None: Current index.
        """
        return self._loader.directory

    def info(self) -> DirectoryInfo:
        """Describe the current state for the status resource.

        Returns:
            DirectoryInfo: Snapshot of the service state.
        """
        loader = self._loader
        directory = loader.directory
        failure = loader.failure
        return DirectoryInfo(
            status=loader.status,
            companies=len(directory) if directory else 0,
            listed=directory.listed_count if directory else 0,
            loaded_at=directory.loaded_at if directory else None,
            source=loader.source,
            error=failure.reason if failure else None,
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
        try:
            return await self._loader.wait(seconds, on_progress=progress)
        except NotConfiguredError:
            error: ServerError = ConfigurationError(API_KEY_MISSING)
        except DirectoryNotReadyError as unavailable:
            error = _unavailable(unavailable)
        raise error

    async def run(self) -> None:
        """Load the directory, then keep it fresh until cancelled.

        Failed refreshes keep serving the previous directory and back off for an hour, so a
        persistent upstream problem does not spend the API key's daily quota.
        """
        await self._loader.run()


def _unavailable(error: DirectoryNotReadyError) -> DirectoryUnavailableError:
    """Explain why no directory is available yet.

    Args:
        error (DirectoryNotReadyError): The loader's structured explanation.

    Returns:
        DirectoryUnavailableError: Error for the caller, with a corp-code hint.
    """
    if error.failure is not None:
        message = f"The company directory could not be loaded ({error.failure.reason}); the server is retrying in the background. {_HINT}"
        return DirectoryUnavailableError(message)
    elapsed = int(error.elapsed_s)
    message = f"The company directory is still loading ({elapsed} s so far; OpenDART can take several minutes). Retry shortly. {_HINT}"
    return DirectoryUnavailableError(message)


def _reason(error: Exception) -> str:
    """Describe a failed archive download safely.

    Args:
        error (Exception): What the download raised: an SDK, server, archive, or timeout
            failure, or a bug.

    Returns:
        str: Message for the status resource and tool errors.
    """
    if isinstance(error, OpenDARTError):
        return str(translate(error))
    if isinstance(error, ServerError | DirectoryError | TimeoutError):
        return str(error) or type(error).__name__
    # A bug must not leave the directory "loading" forever with nothing logged.
    logger.error("Company directory load failed unexpectedly", exc_info=error)
    return f"unexpected {type(error).__name__}"
