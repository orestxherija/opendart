"""read_filing: outline, read, and search original filing documents."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_analysis.documents import DEFAULT_MAX_CHARS, MAX_CHARS_CAP, LabelMode
from opendart_mcp.app.annotations import READ_ONLY, TASK_OPTIONAL
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.documents import FilingMode, ReadFilingResult
from opendart_mcp.render.documents import render_read_filing
from opendart_mcp.services.documents import FilingRequest, open_filing, wait_seconds


@tool(
    name="read_filing",
    version="1.0.0",
    title="Read a filing",
    tags={"documents"},
    annotations=READ_ONLY,
    task=TASK_OPTIONAL,
)
@markdown_view(render_read_filing)
async def read_filing(
    *,
    filing_number: Annotated[
        str,
        Field(
            pattern=r"^\d{14}$",
            description="14-digit number from search_filings or source_filings.",
        ),
    ],
    mode: Annotated[
        FilingMode, Field(description="outline: section map; read: one page; search: passages.")
    ] = "outline",
    section: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=200,
            description="Outline ID, alias (business, mdna, consolidated_notes, ...), or heading text.",
        ),
    ] = None,
    query: Annotated[
        str | None,
        Field(min_length=1, max_length=200, description="Search terms; Korean finds body text."),
    ] = None,
    document: Annotated[
        str,
        Field(
            min_length=1, max_length=64, description="main, or an attachment key from the outline."
        ),
    ] = "main",
    offset: Annotated[int, Field(ge=0, description="Character offset of the page to read.")] = 0,
    max_chars: Annotated[
        int, Field(ge=500, le=MAX_CHARS_CAP, description="Page size in characters.")
    ] = DEFAULT_MAX_CHARS,
    labels: Annotated[
        LabelMode, Field(description="Language of headings and table labels.")
    ] = "english",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> ReadFilingResult:
    """Open an original filing: its outline, one page of its text, or passages matching terms.

    Documents are the Korean originals; headings and table labels are given in English
    where the filing provides them, and you translate the prose. Start with the outline to
    see sections and attachments, then read a section by ID or alias one page at a time,
    following next_offset, or search it: Korean terms such as 전환사채 find body text,
    English terms match headings and labels. Use it for KRX disclosures, business
    descriptions, notes, and anything the structured tools lack. Large reports can take a
    minute to download the first time; if told the download is still in progress, repeat
    the same call.

    Args:
        filing_number (str): Filing to open.
        mode (FilingMode): What to return.
        section (str | None): Section to read or search; omit for the whole document.
        query (str | None): Search terms for mode="search".
        document (str): Document of the archive.
        offset (int): Start of the page, from next_offset or a search hit.
        max_chars (int): Characters per page.
        labels (LabelMode): Heading and label language.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        ReadFilingResult: The requested filing outline, text page, or matching passages.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    request = FilingRequest(
        filing_number=filing_number,
        mode=mode,
        section=section,
        query=query,
        document=document,
        offset=offset,
        max_chars=max_chars,
        labels=labels,
    )
    wait_s = wait_seconds(state, background=ctx.is_background_task)
    return await open_filing(state, request, wait_s=wait_s, progress=Reporter(ctx))


TOOLS = (read_filing,)
