"""The server status resource, ``opendart://server/status``."""

from __future__ import annotations

from typing import Final

from fastmcp.dependencies import Depends
from fastmcp.resources import resource
from mcp.types import Annotations

from opendart_mcp.app.state import get_state
from opendart_mcp.core.state import AppState
from opendart_mcp.services.status import server_status

OPERATIONS: Final = Annotations(audience=["user", "assistant"], priority=0.2)
"""Operational context, useful to the user and occasionally to the model."""


@resource(
    "opendart://server/status",
    name="server_status",
    version="1.0.0",
    title="Server status",
    description="Server health and usage: KST time, version, whether an API key is configured, company directory state, OpenDART requests today, cache statistics, per-component usage, and non-secret settings.",
    mime_type="application/json",
    tags={"reference"},
    annotations=OPERATIONS,
)
async def status_resource(*, state: AppState = Depends(get_state)) -> str:
    """Server status as JSON.

    Args:
        state (AppState): Server state, injected.

    Returns:
        str: Status JSON.
    """
    return server_status(state).model_dump_json(exclude_none=True)


RESOURCES = (status_resource,)
