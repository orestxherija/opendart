"""Allowlisted diagnostics and metrics callbacks; app.http_observability.

Use static upstream/operation labels, never request data::

    try:
        invoice = await observe_call(
            lambda: api.fetch_invoice(invoice_id),
            upstream="billing", operation="fetch_invoice", emit=metrics.observe,
        )
    except BillingError as error:
        log_failure(logger, error, upstream="billing", operation="fetch_invoice")
        raise

This does not sanitize other loggers or framework exception handlers. Original
exceptions and causes remain intact for the caller's restricted debugging path.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal, TypeVar

import httpx2

T = TypeVar("T")


def safe_failure_fields(
    error: BaseException, *, upstream: str, operation: str
) -> dict[str, object]:
    """Describe a failure without reading messages, request data, or traceback.

    Labels must be trusted application constants. Limit traversal to eight
    distinct exceptions, including causes, contexts, and grouped errors. Class
    names come from application/library code; arbitrary error text is omitted.
    """
    fields: dict[str, object] = {"upstream": upstream, "operation": operation}
    types: list[str] = []
    seen: set[int] = set()
    pending = [error]
    while pending and len(seen) < 8:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        types.append(type(current).__name__)
        if isinstance(current, httpx2.HTTPStatusError):
            fields.setdefault("status", current.response.status_code)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions[:8]))
        cause = current.__cause__ or current.__context__
        if cause is not None:
            pending.append(cause)
    fields["error_types"] = types
    return fields


def log_failure(
    logger: logging.Logger,
    error: BaseException,
    *,
    upstream: str,
    operation: str,
) -> None:
    """Emit a structured record with no exception text or traceback attached."""
    logger.warning(
        "upstream call failed",
        extra={
            "http": safe_failure_fields(error, upstream=upstream, operation=operation)
        },
        exc_info=False,
        stack_info=False,
    )


@dataclass(frozen=True)
class Observation:
    """Low-cardinality labels and one elapsed-time measurement, without data."""

    upstream: str
    operation: str
    layer: Literal["operation", "attempt"]
    outcome: Literal["success", "error", "cancelled"]
    duration_seconds: float


async def observe_call(
    call: Callable[[], Awaitable[T]],
    *,
    upstream: str,
    operation: str,
    emit: Callable[[Observation], None],
    layer: Literal["operation", "attempt"] = "operation",
) -> T:
    """Observe the entire callable, preserving its result, error, or cancellation.

    The callback must be fast and nonblocking. Ordinary exporter failures emit
    a fixed diagnostic and cannot replace an upstream outcome. A response's
    status counts as an error only if the callable raises for it. Wrap body
    consumption inside the callable to include transfer time.
    """
    start = monotonic()
    outcome: Literal["success", "error", "cancelled"] = "success"
    try:
        return await call()
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        observation = Observation(
            upstream, operation, layer, outcome, monotonic() - start
        )
        try:
            emit(observation)
        except Exception:
            logging.getLogger(__name__).warning("HTTP observer failed", exc_info=False)
