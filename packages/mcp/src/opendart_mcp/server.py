"""OpenDART MCP server: assembly and the local Streamable HTTP entry point."""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING, Any, Final

from fastmcp import FastMCP
from fastmcp_tasks import TasksExtension
from starlette.responses import JSONResponse

from opendart_mcp.app.logs import configure_logging, quiet_expected_errors
from opendart_mcp.app.middleware import build_middleware
from opendart_mcp.app.registry import register_components
from opendart_mcp.app.state import make_lifespan
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.redaction import protect_secrets
from opendart_mcp.instructions import INSTRUCTIONS
from opendart_mcp.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from starlette.requests import Request
    from starlette.responses import Response

    from opendart import OpenDARTSettings
    from opendart_mcp.core.runtime import TransportFactory
    from opendart_mcp.settings import Settings

VERSION: Final = version("opendart-mcp")
# Keep localhost protections when Docker needs a wildcard bind; ports are matched by glob.
ALLOWED_HOSTS: Final = ["127.0.0.1:*", "localhost:*"]
ALLOWED_ORIGINS: Final = ["http://127.0.0.1:*", "http://localhost:*"]


async def health(request: Request) -> Response:
    """Report liveness without spending a tool slot.

    Args:
        request (Request): Incoming request.

    Returns:
        Response: JSON with the status and server version.
    """
    del request
    return JSONResponse({"status": "ok", "version": VERSION})


def create_server(
    settings: Settings | None = None,
    *,
    api: OpenDARTSettings | None = None,
    transport: TransportFactory | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastMCP[dict[str, Any]]:
    """Build the server; tests inject upstream settings, a transport factory, and a clock.

    Args:
        settings (Settings | None): Server configuration; None loads it from the environment.
        api (OpenDARTSettings | None): Upstream settings; None reads the SDK environment.
        transport (TransportFactory | None): Transport factory for every SDK client.
        clock (Callable[[], datetime] | None): Aware clock; None uses the system clock.

    Returns:
        FastMCP[dict[str, Any]]: Server ready to run or to serve an in-memory client.
    """
    settings = settings or get_settings()
    protect_secrets()
    quiet_expected_errors()
    metrics = Metrics()
    cache_ttl = settings.http.cache_ttl
    server: FastMCP[dict[str, Any]] = FastMCP(
        "OpenDART",
        instructions=INSTRUCTIONS,
        version=VERSION,
        website_url="https://github.com/orestxherija/opendart",
        lifespan=make_lifespan(settings, metrics, api=api, transport=transport, clock=clock),
        middleware=build_middleware(settings, metrics),
        on_duplicate="error",
        mask_error_details=True,
        list_page_size=settings.http.list_page_size,
        cache_ttl=cache_ttl,
        cache_scope="private" if cache_ttl is not None else None,
    )
    server.add_extension(
        TasksExtension(
            url="memory://", name=settings.tasks.queue, concurrency=settings.tasks.concurrency
        )
    )
    register_components(server, settings)
    server.custom_route("/health", methods=["GET"], include_in_schema=False)(health)
    return server


server = create_server()


def main() -> None:
    """Serve MCP requests over Streamable HTTP on the local machine."""
    settings = get_settings().http
    configure_logging()
    server.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path="/mcp",
        show_banner=False,
        host_origin_protection=True,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
    )


if __name__ == "__main__":
    main()
