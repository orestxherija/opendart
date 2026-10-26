"""Company filing index, filing outline, and filing section resources."""

from __future__ import annotations

from fastmcp.dependencies import Depends
from fastmcp.resources import resource

from opendart_mcp.app.annotations import FOR_ASSISTANT
from opendart_mcp.app.errors import resource_errors
from opendart_mcp.app.state import get_state
from opendart_mcp.core.state import AppState
from opendart_mcp.services.documents import filing_outline, filing_section
from opendart_mcp.services.filings import DEFAULT_SINCE, company_filing_index


@resource(
    "opendart://company/{corp_code}/filings{?since,category}",
    name="company_filings",
    version="1.0.0",
    title="Company filing index",
    description="One company's filings, newest first, up to 100 (same items as search_filings). Defaults: last 90 days, every category; since takes an ISO date or 30d/6m/2y, category a name from opendart://reference/filing-categories.",
    mime_type="application/json",
    tags={"filings"},
    annotations=FOR_ASSISTANT,
)
@resource_errors
async def company_filings_resource(
    *,
    corp_code: str,
    since: str = DEFAULT_SINCE,
    category: str | None = None,
    state: AppState = Depends(get_state),
) -> str:
    """Company filing index as JSON.

    Args:
        corp_code (str): 8-digit DART corporation code.
        since (str): Filing-window start as a relative interval or ISO date.
        category (str | None): Filing category name, or None to include every category.
        state (AppState): Server state, injected.

    Returns:
        str: Filing index JSON.
    """
    result = await company_filing_index(state, corp_code, since=since, category=category)
    return result.model_dump_json(exclude_none=True)


@resource(
    "opendart://filing/{filing_number}",
    name="filing_outline",
    version="1.0.0",
    title="Filing outline",
    description="Metadata and outline of one filing's main document: form, company, filing date, amendment summary, sections, attachments, and DART viewer link (same as read_filing with mode=outline).",
    mime_type="application/json",
    tags={"documents"},
    annotations=FOR_ASSISTANT,
)
@resource_errors
async def filing_outline_resource(
    *, filing_number: str, state: AppState = Depends(get_state)
) -> str:
    """Filing outline as JSON.

    Args:
        filing_number (str): 14-digit filing number.
        state (AppState): Server state, injected.

    Returns:
        str: Outline JSON.
    """
    result = await filing_outline(state, filing_number)
    return result.model_dump_json(exclude_none=True)


@resource(
    "opendart://filing/{filing_number}/sections/{section_id}",
    name="filing_section",
    version="1.0.0",
    title="Filing section",
    description="One section of a filing's main document as Markdown with English headings and labels, unpaged; section_id is an outline ID or alias. Long sections are easier to page with read_filing.",
    mime_type="text/markdown",
    tags={"documents"},
    annotations=FOR_ASSISTANT,
)
@resource_errors
async def filing_section_resource(
    *, filing_number: str, section_id: str, state: AppState = Depends(get_state)
) -> str:
    """One filing section as Markdown.

    Args:
        filing_number (str): 14-digit filing number.
        section_id (str): Outline ID or section alias.
        state (AppState): Server state, injected.

    Returns:
        str: Section Markdown.
    """
    return await filing_section(state, filing_number, section_id)


RESOURCES = (company_filings_resource, filing_outline_resource, filing_section_resource)
