"""The company profile resource, ``opendart://company/{corp_code}``."""

from __future__ import annotations

from fastmcp.dependencies import Depends
from fastmcp.resources import resource

from opendart_mcp.app.annotations import FOR_ASSISTANT
from opendart_mcp.app.errors import resource_errors
from opendart_mcp.app.state import get_state
from opendart_mcp.core.state import AppState
from opendart_mcp.services.profile import company_profile


@resource(
    "opendart://company/{corp_code}",
    name="company_profile",
    version="1.0.0",
    title="Company profile",
    description="Identity, reference facts, and latest periodic report for one company (same payload as get_company_profile).",
    mime_type="application/json",
    tags={"identity"},
    annotations=FOR_ASSISTANT,
)
@resource_errors
async def company_resource(*, corp_code: str, state: AppState = Depends(get_state)) -> str:
    """Company profile as JSON.

    Args:
        corp_code (str): 8-digit DART corporation code.
        state (AppState): Server state, injected.

    Returns:
        str: Profile JSON.
    """
    result = await company_profile(state, corp_code)
    return result.model_dump_json(exclude_none=True)


RESOURCES = (company_resource,)
