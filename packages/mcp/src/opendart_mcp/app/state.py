"""FastMCP lifespan and the typed dependency components use to reach server state."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final

from fastmcp.dependencies import CurrentContext

from opendart_mcp.core.runtime import open_state
from opendart_mcp.core.state import AppState

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime

    from fastmcp import Context, FastMCP

    from opendart import OpenDartSettings
    from opendart_mcp.core.metrics import Metrics
    from opendart_mcp.core.runtime import TransportFactory
    from opendart_mcp.settings import Settings

    type Lifespan = Callable[[FastMCP[dict[str, Any]]], AbstractAsyncContextManager[dict[str, Any]]]

STATE_KEY: Final = "state"


def make_lifespan(
    settings: Settings,
    metrics: Metrics,
    *,
    api: OpenDartSettings | None = None,
    transport: TransportFactory | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Lifespan:
    """Build the server lifespan; tests inject a transport, key, and clock.

    The lifespan runs once per process over HTTP and once per in-memory client.

    Args:
        settings (Settings): Server configuration.
        metrics (Metrics): Usage counters shared with the middleware.
        api (OpenDartSettings | None): Upstream settings; None reads the SDK environment.
        transport (TransportFactory | None): Transport factory for every SDK client.
        clock (Callable[[], datetime] | None): Aware clock; None uses the system clock.

    Returns:
        Lifespan: Callable FastMCP enters on startup.
    """
    options: dict[str, Any] = {"api": api, "transport": transport}
    if clock is not None:
        options["clock"] = clock

    @asynccontextmanager
    async def lifespan(server: FastMCP[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        """Open server state for the server's lifetime.

        Args:
            server (FastMCP[dict[str, Any]]): The server being started.

        Yields:
            dict[str, Any]: Lifespan context holding the state.
        """
        del server
        async with open_state(settings, metrics=metrics, **options) as state:
            yield {STATE_KEY: state}

    return lifespan


def get_state(ctx: Context = CurrentContext()) -> AppState:
    """Return the server state; use as ``state: AppState = Depends(get_state)``.

    Works in foreground calls and in background tasks.

    Args:
        ctx (Context): Current request context, injected by FastMCP.

    Returns:
        AppState: Lifespan state.

    Raises:
        RuntimeError: The lifespan did not run, which is a wiring bug.
    """
    state = ctx.lifespan_context.get(STATE_KEY)
    if not isinstance(state, AppState):
        message = "OpenDART server state is unavailable; the lifespan did not run."
        raise RuntimeError(message)  # noqa: TRY004 - a wiring failure, not a caller type error
    return state
