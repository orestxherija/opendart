"""MCP progress reporting that works for foreground calls and background tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import Context


class Reporter:
    """Send progress with a strictly increasing counter and a descriptive message.

    In the foreground this becomes ``notifications/progress`` (only when the client sent a
    progress token); in a background task the message becomes the task status message.
    Use it as the ``progress`` callback that services accept.
    """

    def __init__(self, ctx: Context, *, total: int | None = None) -> None:
        """Bind to a request context.

        Args:
            ctx (Context): Current request context.
            total (int | None): Expected number of steps, when known.
        """
        self._ctx = ctx
        self._total = total
        self._count = 0

    async def __call__(self, message: str) -> None:
        """Report one step.

        Args:
            message (str): What is happening, with counts where useful ("3/20 companies").
        """
        self._count += 1
        total = self._total if self._total is not None and self._total >= self._count else None
        await self._ctx.report_progress(self._count, total, message)
