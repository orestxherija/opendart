"""Build and tear down server state: SDK clients, caches, and background loaders.

This module is framework-independent; the FastMCP lifespan wraps ``open_state``. Tests
inject a transport factory so every SDK client talks to a fake upstream.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError
from pydantic_settings import SettingsError

from opendart import OpenDart, OpenDartSettings, get_settings
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.metrics import count_upstream
from opendart_mcp.core.redaction import protect_secrets
from opendart_mcp.core.state import AppState
from opendart_mcp.documents.store import DocumentStore
from opendart_mcp.domain.dates import KST
from opendart_mcp.services.companies import Companies
from opendart_mcp.services.directory import DirectoryService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    import httpx2

    from opendart_mcp.core.gateway import CacheKey
    from opendart_mcp.core.metrics import Metrics
    from opendart_mcp.settings import Settings

logger = logging.getLogger(__name__)

type TransportFactory = Callable[[], httpx2.AsyncBaseTransport]

# Archives above this size are refused before they are read into memory.
DOCUMENT_DOWNLOAD_LIMIT = 32 * 1024 * 1024


def load_api_settings() -> OpenDartSettings | None:
    """Read the SDK's upstream settings, tolerating a missing or invalid key.

    Returns:
        OpenDartSettings | None: Upstream settings, or None when no usable key is set.
    """
    try:
        return get_settings().api
    except ValidationError, SettingsError:
        logger.warning("No valid OpenDART API key; tools will explain how to configure one")
        return None


def _client(
    api: OpenDartSettings, transport: TransportFactory | None, **overrides: float
) -> OpenDart:
    """Create an SDK client with adjusted timeouts or limits.

    Args:
        api (OpenDartSettings): Base upstream settings, including the key.
        transport (TransportFactory | None): Optional transport factory for tests.
        **overrides (float): OpenDartSettings fields to replace.

    Returns:
        OpenDart: Client owning its connection pool.
    """
    settings = OpenDartSettings.model_validate(api.model_dump() | overrides)
    return OpenDart(settings, transport=transport() if transport else None)


@dataclass(frozen=True, slots=True)
class _Upstream:
    """Upstream access created when an API key is configured."""

    gateway: Gateway
    fetch_directory: Callable[[], Awaitable[bytes]]
    documents: DocumentStore


async def _open_upstream(
    stack: AsyncExitStack,
    settings: Settings,
    *,
    api: OpenDartSettings,
    transport: TransportFactory | None,
    cache: TTLCache[CacheKey, object],
    clock: Callable[[], datetime],
) -> _Upstream:
    """Open the SDK clients and build the gateway, directory fetcher, and document store.

    JSON services use the upstream timeouts; directory and document downloads use a
    second client with the longer document timeouts and a download size limit.

    Args:
        stack (AsyncExitStack): Exit stack that closes the clients and the document store.
        settings (Settings): Server configuration.
        api (OpenDartSettings): Upstream settings, including the key.
        transport (TransportFactory | None): Transport factory for tests.
        cache (TTLCache[CacheKey, object]): Response cache for the gateway.
        clock (Callable[[], datetime]): Aware clock.

    Returns:
        _Upstream: Gateway, directory fetcher, and document store.
    """
    upstream, documents = settings.upstream, settings.documents
    json_client = await stack.enter_async_context(
        _client(api, transport, timeout=upstream.timeout, connect_timeout=upstream.connect_timeout)
    )
    bulk_client = await stack.enter_async_context(
        _client(
            api,
            transport,
            timeout=documents.timeout,
            connect_timeout=documents.connect_timeout,
            max_download_bytes=DOCUMENT_DOWNLOAD_LIMIT,
        )
    )
    gateway = Gateway(
        json_client,
        cache=cache,
        concurrency=upstream.max_concurrency,
        retry_delay=upstream.retry_delay,
        clock=clock,
    )
    fetch_document = _counted(gateway, "document", bulk_client.disclosures.document)
    store = DocumentStore(
        lambda number: fetch_document(filing_number=number),
        max_rendered_chars=documents.cache_chars,
    )
    stack.push_async_callback(store.aclose)
    fetch_directory = _counted(
        gateway, "corporation_codes", bulk_client.disclosures.corporation_codes
    )
    return _Upstream(gateway, fetch_directory, store)


def _counted[**P, R](
    gateway: Gateway, operation: str, function: Callable[P, Awaitable[R]]
) -> Callable[P, Awaitable[R]]:
    """Count bulk downloads, which bypass the gateway, against the daily quota.

    Args:
        gateway (Gateway): Gateway holding the usage counters.
        operation (str): Name recorded per operation.
        function (Callable[P, Awaitable[R]]): Download coroutine function.

    Returns:
        Callable[P, Awaitable[R]]: The same function, counting each call.
    """

    async def counted(*args: P.args, **kwargs: P.kwargs) -> R:
        """Call the wrapped download after recording its upstream usage.

        Args:
            *args (P.args): Positional arguments forwarded to the download function.
            **kwargs (P.kwargs): Keyword arguments forwarded to the download function.

        Returns:
            R: Result returned by the download function.
        """
        gateway.usage.record(operation, gateway.now())
        count_upstream()
        return await function(*args, **kwargs)

    return counted


@asynccontextmanager
async def open_state(
    settings: Settings,
    *,
    metrics: Metrics,
    api: OpenDartSettings | None = None,
    transport: TransportFactory | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(KST),
) -> AsyncIterator[AppState]:
    """Create server state and run its background loaders until the context exits.

    Args:
        settings (Settings): Server configuration.
        metrics (Metrics): Usage counters shared with the middleware.
        api (OpenDartSettings | None): Upstream settings; None reads the SDK environment.
        transport (TransportFactory | None): Transport factory used by every SDK client.
        clock (Callable[[], datetime]): Aware clock for dates and ages.

    Yields:
        AppState: Ready-to-use state; the directory may still be loading.
    """
    # The API key travels in request URLs, which the HTTP client logs; redact before any
    # client exists, whatever the caller's logging setup.
    protect_secrets()
    api = api or load_api_settings()
    cache: TTLCache[CacheKey, object] = TTLCache(max_weight=settings.upstream.cache_records)
    # FastMCP enters and exits the lifespan in different tasks, so background work uses
    # plain asyncio tasks rather than an anyio task group spanning the yield.
    async with AsyncExitStack() as stack:
        upstream = None
        if api is not None:
            upstream = await _open_upstream(
                stack, settings, api=api, transport=transport, cache=cache, clock=clock
            )
        gateway = upstream.gateway if upstream else None
        fetch_directory = upstream.fetch_directory if upstream else None
        directory = DirectoryService(fetch_directory, settings.directory, clock=clock)
        loader = asyncio.create_task(directory.run(), name="opendart-directory")
        try:
            yield AppState(
                settings=settings,
                gateway=gateway,
                cache=cache,
                directory=directory,
                companies=Companies(directory, gateway, wait=settings.directory.wait),
                metrics=metrics,
                documents=upstream.documents if upstream else None,
                clock=clock,
                started=clock(),
            )
        finally:
            loader.cancel()
            await asyncio.gather(loader, return_exceptions=True)
