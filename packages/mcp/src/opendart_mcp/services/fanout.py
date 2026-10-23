"""Run independent upstream calls concurrently, keeping expected errors unwrapped.

An anyio task group raises an exception group when a child fails, but the tool layer
expects a plain ``ServerError`` with an actionable message. Expected failures are collected
instead, and the first one is raised again once every call has finished.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio

from opendart_mcp.core.errors import ServerError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence


async def gather[T](calls: Sequence[Callable[[], Awaitable[T]]]) -> list[T]:
    """Await calls concurrently and return their results in call order.

    Args:
        calls (Sequence[Callable[[], Awaitable[T]]]): Zero-argument coroutine functions.

    Returns:
        list[T]: One result per call, in order.

    Raises:
        ServerError: The first expected failure among the calls.
    """
    results: dict[int, T] = {}
    errors: list[ServerError] = []

    async def run(index: int, call: Callable[[], Awaitable[T]]) -> None:
        """Run one call and collect expected failures for propagation afterward.

        Args:
            index (int): Position used to restore the input order.
            call (Callable[[], Awaitable[T]]): Zero-argument coroutine function to await.
        """
        try:
            results[index] = await call()
        except ServerError as error:
            errors.append(error)

    async with anyio.create_task_group() as group:
        for index, call in enumerate(calls):
            group.start_soon(run, index, call)
    if errors:
        raise errors[0]
    return [results[index] for index in range(len(calls))]
