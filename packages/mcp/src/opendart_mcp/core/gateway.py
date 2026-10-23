"""The single path from components to OpenDART JSON services.

Every call is cached by SDK method and arguments, coalesced with identical in-flight calls,
bounded by a concurrency limit, retried once on transient failures, and translated into
actionable errors. OpenDART's "no data" status becomes None: an empty answer, not a failure.
"""

from __future__ import annotations

import functools
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, cast

import anyio
from opentelemetry import trace
from pydantic import ValidationError

from opendart import (
    APIRejectedError,
    NoDataError,
    OpenDartError,
    QuotaExceededError,
    RejectedError,
    ServiceUnavailableError,
    UnavailableError,
)
from opendart_mcp.core.cache import MISSING, SingleFlight
from opendart_mcp.core.errors import (
    MAINTENANCE,
    QUOTA_EXHAUSTED,
    UNAVAILABLE,
    ConfigurationError,
    InvalidArgumentError,
    QuotaExhaustedError,
    ServerError,
    UpstreamError,
)
from opendart_mcp.core.metrics import count_upstream, uncount_upstream
from opendart_mcp.core.ttl import FILINGS
from opendart_mcp.domain.dates import KST

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from opendart import OpenDart
    from opendart_mcp.core.cache import TTLCache

type CacheKey = tuple[str, tuple[Hashable, ...], tuple[tuple[str, Hashable], ...]]

# OpenDART statuses that mean the key itself is unusable: unregistered, suspended,
# disallowed IP address, or expired.
_KEY_STATUSES = frozenset({"010", "011", "012", "901"})
_TRACER = trace.get_tracer("opendart_mcp.gateway")
_TRANSLATIONS: tuple[tuple[type[OpenDartError], type[ServerError], str], ...] = (
    (QuotaExceededError, QuotaExhaustedError, QUOTA_EXHAUSTED),
    (ServiceUnavailableError, UpstreamError, MAINTENANCE),
    (UnavailableError, UpstreamError, UNAVAILABLE),
)


def _freeze(value: object) -> Hashable:
    """Convert list arguments to tuples so they can form part of a cache key.

    Args:
        value (object): SDK keyword argument value.

    Returns:
        Hashable: The value, with lists converted to tuples.
    """
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value if isinstance(value, Hashable) else repr(value)


def cache_key(
    function: Callable[..., object], args: tuple[object, ...], kwargs: dict[str, object]
) -> CacheKey:
    """Build a deterministic key from an SDK method and its arguments.

    Args:
        function (Callable[..., object]): Bound SDK method; its qualified name identifies it.
        args (tuple[object, ...]): Positional arguments.
        kwargs (dict[str, object]): Keyword arguments.

    Returns:
        CacheKey: Hashable key independent of keyword order.
    """
    frozen = tuple(sorted((name, _freeze(value)) for name, value in kwargs.items()))
    return (function.__qualname__, tuple(_freeze(arg) for arg in args), frozen)


def translate(error: OpenDartError) -> ServerError:
    """Map an SDK failure to an actionable server error.

    Args:
        error (OpenDartError): Failure raised by the SDK.

    Returns:
        ServerError: Error whose message tells the model what to do next.
    """
    if isinstance(error, APIRejectedError) and error.status in _KEY_STATUSES:
        return ConfigurationError(
            f"OpenDART rejected the API key (status {error.status}). Check OPENDART_API__API_KEY and the key's registration."
        )
    for source, target, message in _TRANSLATIONS:
        if isinstance(error, source):
            return target(message)
    status = f"status {error.status}" if error.status else type(error).__name__
    if isinstance(error, RejectedError):
        message = f"OpenDART rejected the request to {error.operation} ({status}). Check the arguments: codes, dates, report periods, and at most 100 companies per call."
        return UpstreamError(message)
    return UpstreamError(
        f"OpenDART could not answer {error.operation} ({status}). Retry later or narrow the request; if the problem persists, use another tool for the same data."
    )


def _weight(result: object) -> int:
    """Estimate a response's cache weight from its record count.

    Args:
        result (object): SDK response model or None.

    Returns:
        int: One plus the number of list records.
    """
    records = getattr(result, "list", None)
    return 1 + (len(records) if isinstance(records, list) else 0)


@dataclass(slots=True)
class Usage:
    """Upstream request counters, reset at midnight KST like OpenDART's daily quota.

    Attributes:
        day (str): ISO date in KST that the daily counter refers to.
        today (int): Requests sent to OpenDART on that day, including retries.
        total (int): Requests sent since the server started.
        failures (int): Requests that failed after translation, since start.
    """

    day: str = ""
    today: int = 0
    total: int = 0
    failures: int = 0
    by_operation: dict[str, int] = field(default_factory=dict)

    def record(self, operation: str, now: datetime) -> None:
        """Count one upstream request.

        Args:
            operation (str): SDK method name, for per-operation counts.
            now (datetime): Current time; converted to KST to select the day.
        """
        day = now.astimezone(KST).date().isoformat()
        if day != self.day:
            self.day, self.today = day, 0
        self.today += 1
        self.total += 1
        self.by_operation[operation] = self.by_operation.get(operation, 0) + 1

    def retract(self, operation: str) -> None:
        """Undo one recorded request that was never sent.

        Args:
            operation (str): SDK method name.
        """
        self.today = max(self.today - 1, 0)
        self.total = max(self.total - 1, 0)
        remaining = self.by_operation.get(operation, 0) - 1
        if remaining > 0:
            self.by_operation[operation] = remaining
        else:
            self.by_operation.pop(operation, None)


class Gateway:
    """Cached, coalesced, bounded, and retried access to the SDK's JSON services."""

    def __init__(
        self,
        sdk: OpenDart,
        *,
        cache: TTLCache[CacheKey, object],
        concurrency: int,
        retry_delay: float = 1.0,
        clock: Callable[[], datetime] = lambda: datetime.now(KST),
    ) -> None:
        """Wrap an SDK client; the gateway does not own or close it.

        Args:
            sdk (OpenDart): Authenticated SDK client.
            cache (TTLCache[CacheKey, object]): Shared response cache.
            concurrency (int): Maximum simultaneous upstream requests.
            retry_delay (float): Seconds to wait before the single retry.
            clock (Callable[[], datetime]): Aware clock used for daily usage counters.
        """
        self.sdk = sdk
        self.usage = Usage()
        self._cache = cache
        self._flight: SingleFlight[CacheKey, object] = SingleFlight()
        self._limiter = anyio.Semaphore(concurrency)
        self._retry_delay = retry_delay
        self._clock = clock

    def now(self) -> datetime:
        """Current time from the gateway's clock.

        Returns:
            datetime: Aware current time.
        """
        return self._clock()

    @property
    def in_flight(self) -> int:
        """Number of distinct upstream calls currently running.

        Returns:
            int: In-flight call count.
        """
        return self._flight.in_flight

    async def call[**P, R](
        self, ttl: float, function: Callable[P, Awaitable[R]], /, *args: P.args, **kwargs: P.kwargs
    ) -> R | None:
        """Call an SDK method through the cache, returning None when OpenDART has no data.

        Args:
            ttl (float): Seconds to cache the answer, including a "no data" answer; 0 skips
                the cache.
            function (Callable[P, Awaitable[R]]): Bound SDK method, such as
                ``gateway.sdk.disclosures.company``.
            *args (P.args): Positional arguments for the method.
            **kwargs (P.kwargs): Keyword arguments for the method.

        Returns:
            R | None: The validated response, or None for OpenDART status 013.

        Raises:
            ServerError: The request was invalid, rejected, or failed after one retry.
        """
        key = cache_key(function, args, kwargs)
        cached = self._cache.get(key)
        if cached is not MISSING:
            return cast("R | None", cached)
        bound = functools.partial(function, *args, **kwargs)
        result = await self._flight.run(key, lambda: self._load(key, ttl, bound))
        return cast("R | None", result)

    async def _load(
        self, key: CacheKey, ttl: float, call: Callable[[], Awaitable[object]]
    ) -> object:
        """Fetch once with a single retry, then cache the answer.

        Args:
            key (CacheKey): Cache key for the call.
            ttl (float): Seconds to keep the answer.
            call (Callable[[], Awaitable[object]]): Bound SDK call.

        Returns:
            object: Response model or None.

        Raises:
            ServerError: The call failed after translation.
        """
        try:
            result = await self._fetch(key[0], call)
        except InvalidArgumentError:
            raise
        except ServerError:
            self.usage.failures += 1
            raise
        # "No data" may only mean "not filed yet", so it is rechecked as often as filing lists.
        lifetime = min(ttl, FILINGS) if result is None else ttl
        self._cache.put(key, result, ttl=lifetime, weight=_weight(result))
        return result

    async def _fetch(self, operation: str, call: Callable[[], Awaitable[object]]) -> object:
        """Attempt a call, retrying once after a transient failure.

        Args:
            operation (str): SDK method name used for usage counters.
            call (Callable[[], Awaitable[object]]): Bound SDK call.

        Returns:
            object: Response model or None for "no data".

        Raises:
            ServerError: The call failed permanently or twice.
        """
        try:
            return await self._attempt(operation, call)
        except OpenDartError as error:
            if not isinstance(error, UnavailableError) or isinstance(
                error, QuotaExceededError | ServiceUnavailableError
            ):
                raise translate(error) from error
        await anyio.sleep(self._retry_delay)
        try:
            return await self._attempt(operation, call)
        except OpenDartError as error:
            raise translate(error) from error

    async def _attempt(self, operation: str, call: Callable[[], Awaitable[object]]) -> object:
        """Make one bounded request, mapping "no data" and invalid arguments.

        Args:
            operation (str): SDK method name used for usage counters.
            call (Callable[[], Awaitable[object]]): Bound SDK call.

        Returns:
            object: Response model, or None for OpenDART status 013.

        Raises:
            InvalidArgumentError: The SDK rejected an argument before sending it.
        """
        async with self._limiter:
            self.usage.record(operation, self._clock())
            count_upstream()
            try:
                with _TRACER.start_as_current_span(
                    "opendart.upstream", attributes={"opendart.operation": operation}
                ):
                    return await call()
            except NoDataError:
                return None
            except ValidationError as error:
                # The SDK validates arguments before sending, so nothing reached OpenDART.
                self.usage.retract(operation)
                uncount_upstream()
                fields = ", ".join(str(item["loc"][-1]) for item in error.errors() if item["loc"])
                message = (
                    f"OpenDART would reject these arguments ({fields}); check codes and dates."
                )
                raise InvalidArgumentError(message) from error
