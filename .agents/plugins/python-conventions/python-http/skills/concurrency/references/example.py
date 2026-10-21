"""Bounded task allocation for finite batches; install as app.http_concurrency.

No project settings or HTTP client factory is required. For example::

    upstream_limit = asyncio.Semaphore(12)  # created once in application lifespan

    async def fetch(identifier: str) -> httpx2.Response:
        response = await client.get(f"items/{identifier}")
        response.raise_for_status()
        return response

    responses = await map_bounded(
        identifiers, fetch, limit=4, limiter=upstream_limit, timeout=30.0
    )

The caller owns the input iterable and any resources behind it. Synchronous
iteration must not block the event loop. Adapt identifier validation to the
upstream contract before interpolating paths.
"""

import asyncio
import math
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


class _WorkerCancelled(Exception):
    """Make a cancelled worker stop its TaskGroup instead of silently exiting."""


async def map_bounded(
    items: Iterable[T],
    operation: Callable[[T], Awaitable[R]],
    *,
    limit: int,
    limiter: asyncio.Semaphore | None = None,
    timeout: float | None = None,
) -> list[R]:
    """Map a finite iterable with bounded workers and ordered results.

    At most ``limit`` tasks and ``limit`` uncompleted inputs are retained by
    this function. Completed results require O(n) memory. An optional shared
    semaphore bounds operations across batches, and ``timeout`` covers the
    whole batch, including permit acquisition and worker cleanup.

    A worker failure cancels and drains siblings, then raises an ExceptionGroup.
    Caller cancellation cancels and drains workers. Operations must cooperate
    with cancellation; cleanup can extend beyond the requested timeout.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if timeout is not None and (
        isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0
    ):
        raise ValueError("timeout must be positive and finite")

    inputs = enumerate(items)
    results: dict[int, R] = {}

    async def worker() -> None:
        try:
            for index, item in inputs:
                if limiter is None:
                    results[index] = await operation(item)
                else:
                    async with limiter:
                        results[index] = await operation(item)
        except asyncio.CancelledError as error:
            # TaskGroup treats a cancelled child as successful completion.
            # Signal failure so operation-initiated cancellation stops siblings.
            # The signal is restored to cancellation after the group is drained.
            raise _WorkerCancelled from error

    async with asyncio.timeout(timeout):
        cancelled = False
        try:
            async with asyncio.TaskGroup() as group:
                for _ in range(limit):
                    group.create_task(worker())
        except* _WorkerCancelled:
            # Sibling cancellation must not obscure ordinary worker failures:
            # any other exception subgroup propagates out of this try block.
            cancelled = True
        if cancelled:
            raise asyncio.CancelledError
    return [results[index] for index in range(len(results))]
