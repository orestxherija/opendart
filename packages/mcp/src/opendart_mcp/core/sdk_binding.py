"""Bind service-catalog entries to the SDK client methods that call them.

opendart_analysis.catalog keeps SDK names only as data and never imports the SDK, so the
binding of a ServiceSpec to an open client lives here, on the MCP side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opendart_analysis.catalog import service

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from opendart import OpenDART
    from opendart_analysis.catalog import ServiceSpec


def sdk_method(client: OpenDART, spec: str | ServiceSpec) -> Callable[..., Awaitable[Any]]:
    """Return the bound SDK coroutine function for a service.

    Args:
        client (OpenDART): Open SDK client.
        spec (str | ServiceSpec): Service name or spec.

    Returns:
        Callable[..., Awaitable[Any]]: The method, such as client.major_issues.cvbd_is_decsn;
            call it with the ParamSpec names as keyword arguments.

    Raises:
        KeyError: The service is unknown.
    """
    resolved = service(spec) if isinstance(spec, str) else spec
    method: Callable[..., Awaitable[Any]] = getattr(
        getattr(client, resolved.resource), resolved.name
    )
    return method
