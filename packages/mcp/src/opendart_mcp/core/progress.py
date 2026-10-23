"""Progress callbacks and deadline-bounded waits, independent of the MCP framework.

Services report progress through a plain async callback; the tool layer supplies one that
sends MCP progress notifications (or a task status message in background tasks).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from opendart_mcp.core.errors import StillRunningError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

type Progress = Callable[[str], Awaitable[None]]

HEARTBEAT_SECONDS = 5.0


async def no_progress(message: str) -> None:
    """Discard a progress message.

    Args:
        message (str): Ignored.
    """
    del message


async def with_heartbeat[T](
    work: Awaitable[T],
    progress: Progress,
    *,
    label: str,
    deadline: float,
    every: float = HEARTBEAT_SECONDS,
) -> T:
    """Await shared work, reporting elapsed time, and give up waiting at a deadline.

    Giving up does not cancel the work: callers pass a shared, cancellation-safe awaitable
    (for example a single-flight task) whose result lands in a cache for the retry.

    Args:
        work (Awaitable[T]): Work to wait for.
        progress (Progress): Receives a message every ``every`` seconds while waiting.
        label (str): What is being waited for, used in messages.
        deadline (float): Seconds to wait before raising.
        every (float): Seconds between progress messages.

    Returns:
        T: The work's result.

    Raises:
        StillRunningError: The deadline passed before the work finished.
    """
    task = asyncio.ensure_future(work)
    start = time.monotonic()
    while True:
        remaining = deadline - (time.monotonic() - start)
        if remaining <= 0:
            message = (
                f"{label} is still in progress. Retry in about a minute; the result will be cached."
            )
            raise StillRunningError(message)
        done, _ = await asyncio.wait((task,), timeout=min(every, remaining))
        if done:
            return task.result()
        await progress(f"{label} ({int(time.monotonic() - start)} s elapsed)")
