"""Retrying HTTP calls at the call site.

``send_with_retries`` wraps one logical call. It retries transient failures,
honors ``Retry-After``, backs off with jitter, and returns the last response or
raises the last error to the caller. The factory never retries; the call site
decides, because only it knows what the call does.

In a multi-module project, ``RetrySettings`` belongs in the settings package and
``send_with_retries`` in ``http_retries.py``. They share a file here for
readability.

Example:
    One policy per upstream that needs one, in the root settings::

        class Settings(BaseSettings):
            billing: HttpClientSettings
            billing_retries: RetrySettings = RetrySettings()

    A read, retried on transient failures::

        response = await send_with_retries(
            lambda: client.get(f"invoices/{invoice_id}"), settings.billing_retries
        )
        response.raise_for_status()

    A create, when the provider guarantees deduplication for this key. Keep the
    same key across durable job retries as well as these in-process attempts::

        headers = {"Idempotency-Key": str(uuid.uuid4())}
        response = await send_with_retries(
            lambda: client.post("invoices", json=body, headers=headers),
            settings.billing_retries,
        )
"""

import logging
from asyncio import sleep
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from random import uniform
from typing import Self

import httpx2
from pydantic import Field, model_validator

from app.settings.base import SettingsGroup
from app.settings.types import Attempts, Seconds

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({408, 429, 502, 503, 504})
"""Statuses that signal a temporary condition on the upstream or in between."""

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})
"""Methods that RFC 9110 defines as idempotent."""

NOT_SENT_ERRORS = (httpx2.ConnectError, httpx2.ConnectTimeout)
"""Failures before the request left, so retrying is safe for any method."""

TRANSIENT_ERRORS = (
    *NOT_SENT_ERRORS,
    httpx2.ReadError,
    httpx2.ReadTimeout,
    httpx2.WriteError,
    httpx2.WriteTimeout,
    httpx2.RemoteProtocolError,
)
"""Failures that may succeed on another attempt. ``PoolTimeout`` is excluded:
it means the connection pool is too small, not that the upstream is down."""


class RetrySettings(SettingsGroup):
    """Retry policy for one upstream.

    Attributes:
        max_attempts (int): Total attempts, including the first.
        initial_backoff (float): Upper bound, in seconds, of the first backoff.
        max_backoff (float): Ceiling, in seconds, for any computed backoff.
        max_retry_after (float): Longest ``Retry-After``, in seconds, worth
            waiting for. A longer one ends the retries.
    """

    max_attempts: Attempts = Field(
        default=3, description="Total attempts, including the first."
    )
    initial_backoff: Seconds = Field(
        default=0.5, description="Upper bound of the first backoff, in seconds."
    )
    max_backoff: Seconds = Field(
        default=30.0, description="Ceiling for any computed backoff, in seconds."
    )
    max_retry_after: Seconds = Field(
        default=60.0, description="Longest Retry-After worth waiting for, in seconds."
    )

    @model_validator(mode="after")
    def _check_backoff_bounds(self) -> Self:
        """Ensure the first backoff does not exceed the ceiling.

        Returns:
            Self: The validated instance.

        Raises:
            ValueError: If ``initial_backoff`` is greater than ``max_backoff``.
        """
        if self.initial_backoff > self.max_backoff:
            raise ValueError(
                f"initial_backoff ({self.initial_backoff}) "
                f"must be <= max_backoff ({self.max_backoff})"
            )
        return self


def _is_idempotent(request: httpx2.Request) -> bool:
    """Whether repeating the request cannot repeat its effect."""
    return request.method in IDEMPOTENT_METHODS or "Idempotency-Key" in request.headers


def _backoff(policy: RetrySettings, attempt: int) -> float:
    """Exponential backoff with full jitter for the given attempt (1-based)."""
    ceiling = min(policy.max_backoff, policy.initial_backoff * 2 ** (attempt - 1))
    return uniform(0, ceiling)


def _retry_after(response: httpx2.Response) -> float | None:
    """Seconds the upstream asked to wait, or ``None`` if it did not say.

    Accepts both forms RFC 9110 allows: delta-seconds and an HTTP date.
    """
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _log_retry(
    request: httpx2.Request,
    reason: str,
    attempt: int,
    policy: RetrySettings,
    delay: float,
) -> None:
    """Log one retry without request URLs, identifiers, bodies, or headers."""
    logger.warning(
        "Retrying %s after %s (attempt %d of %d) in %.2fs",
        request.method,
        reason,
        attempt + 1,
        policy.max_attempts,
        delay,
        exc_info=False,
    )


async def send_with_retries(
    send: Callable[[], Awaitable[httpx2.Response]], policy: RetrySettings
) -> httpx2.Response:
    """Send a request, retrying transient failures.

    ``send`` is called once per attempt and must build a fresh request each
    time, so bodies are recreated and auth flows run again. A request is
    retried only if repeating it is safe: an idempotent method, an
    ``Idempotency-Key`` header, or a failure before the request was sent. Header
    presence is an assertion by the caller that this upstream guarantees
    deduplication for that endpoint; the helper cannot discover provider support.

    Args:
        send (Callable[[], Awaitable[httpx2.Response]]): Sends one attempt,
            for example ``lambda: client.get(path)``.
        policy (RetrySettings): The upstream's retry policy.

    Returns:
        httpx2.Response: The first non-retryable response, or the last one when
            the attempts run out or the upstream asks to wait too long. The
            caller checks its status.

    Raises:
        httpx2.HTTPError: The last transport error, once retrying stops.
    """
    attempt = 1
    while True:
        try:
            response = await send()
        except TRANSIENT_ERRORS as error:
            safe = isinstance(error, NOT_SENT_ERRORS) or _is_idempotent(error.request)
            if attempt == policy.max_attempts or not safe:
                raise
            delay = _backoff(policy, attempt)
            _log_retry(error.request, type(error).__name__, attempt, policy, delay)
        else:
            if (
                response.status_code not in RETRYABLE_STATUSES
                or attempt == policy.max_attempts
                or not _is_idempotent(response.request)
            ):
                return response
            requested = _retry_after(response)
            if requested is not None and requested > policy.max_retry_after:
                return response
            delay = requested if requested is not None else _backoff(policy, attempt)
            # Release the connection before waiting.
            await response.aclose()
            _log_retry(
                response.request, str(response.status_code), attempt, policy, delay
            )
        await sleep(delay)
        attempt += 1
