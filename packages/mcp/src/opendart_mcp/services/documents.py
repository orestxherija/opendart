"""Open original filing documents for read_filing, the filing resources, and extractors.

The document store downloads each filing once, outside the gateway, so this module turns the
SDK's and the parser's failures into actionable errors. Waits are bounded: a caller that
gives up leaves the download running, and the retry finds it cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import anyio.to_thread

from opendart import FileUnavailableError, NoDataError, OpenDARTError, ResponseTooLargeError
from opendart_analysis.documents import (
    DEFAULT_MAX_CHARS,
    ArchiveTooLargeError,
    DocumentError,
    DownloadPendingError,
    MalformedArchiveError,
    SectionNotFoundError,
    StoreClosedError,
    UnknownDocumentError,
)
from opendart_mcp.core.errors import (
    InvalidArgumentError,
    StillRunningError,
    UpstreamError,
)
from opendart_mcp.core.gateway import translate
from opendart_mcp.core.progress import no_progress
from opendart_mcp.domain.identifiers import dart_viewer_url, filing_date, is_filing_number
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.documents import (
    DocumentEntry,
    FilingHits,
    FilingInfo,
    FilingOutline,
    FilingPage,
    OutlineSection,
    ReadFilingResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from opendart_analysis.documents import DocumentInfo, LabelMode, ParsedFiling, SectionInfo
    from opendart_mcp.core.errors import ServerError
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.documents import FilingMode

    type _View = tuple[FilingOutline | FilingPage | FilingHits, str, list[str]]

FOREGROUND_WAIT_S: Final = 40.0
"""Longest wait for a download in a foreground call; many hosts time out requests at 60 s."""
BACKGROUND_WAIT_S: Final = 110.0
"""Longest wait in a background task, inside the document client's 120 s deadline."""
SEARCH_HITS: Final = 20


class UnknownFilingError(InvalidArgumentError):
    """OpenDART has no filing with the requested number (status 013)."""


class DocumentUnavailableError(UpstreamError):
    """A filing's document cannot be downloaded or read; other filings may still open."""


_MODE_ARGUMENTS: Final[dict[str, frozenset[str]]] = {
    "outline": frozenset(),
    "read": frozenset({"section", "offset"}),
    "search": frozenset({"section", "query"}),
}
_VIEWER = " Open it in the DART viewer: {url}"
_FAILURES: Final[tuple[tuple[type[Exception], type[ServerError], str], ...]] = (
    (
        DownloadPendingError,
        StillRunningError,
        "Filing {number} is still downloading; OpenDART can take a minute to send large reports. Repeat the same call in about a minute; the document will be cached.",
    ),
    (
        NoDataError,
        UnknownFilingError,
        "OpenDART has no filing {number}. Pass the 14-digit filing_number from search_filings or from a source_filings entry.",
    ),
    (
        FileUnavailableError,
        DocumentUnavailableError,
        "OpenDART cannot provide the document of filing {number} (status 014)." + _VIEWER,
    ),
    (
        ResponseTooLargeError,
        DocumentUnavailableError,
        "Filing {number} is larger than this server downloads (32 MiB compressed)." + _VIEWER,
    ),
    (
        ArchiveTooLargeError,
        DocumentUnavailableError,
        "Filing {number} is too large to open here ({error})." + _VIEWER,
    ),
    (
        MalformedArchiveError,
        DocumentUnavailableError,
        "The document of filing {number} could not be read ({error})." + _VIEWER,
    ),
    (
        TimeoutError,
        UpstreamError,
        "Downloading filing {number} took over two minutes and was stopped; OpenDART is slow right now. Repeat the call to start a fresh download.",
    ),
    (
        StoreClosedError,
        UpstreamError,
        "The server is shutting down and cannot open filing {number}; retry shortly.",
    ),
)


@dataclass(frozen=True, slots=True)
class FilingRequest:
    """What to show from a filing.

    Attributes:
        filing_number (str): 14-digit filing number.
        mode (FilingMode): ``outline``, ``read``, or ``search``.
        section (str | None): Outline ID, alias, or heading text; None for the whole document.
        query (str | None): Search terms, for ``search``.
        document (str): Document key, form code, or member name.
        offset (int): Character offset, for ``read``.
        max_chars (int): Page size, for ``read``.
        labels (LabelMode): Language of headings and labels.
    """

    filing_number: str
    mode: FilingMode = "outline"
    section: str | None = None
    query: str | None = None
    document: str = "main"
    offset: int = 0
    max_chars: int = DEFAULT_MAX_CHARS
    labels: LabelMode = "english"


def wait_seconds(state: AppState, *, background: bool) -> float:
    """Choose how long a call waits for a download before answering that it continues.

    Args:
        state (AppState): Server state; ``documents.wait`` can shorten foreground waits.
        background (bool): Whether the call runs as a background task.

    Returns:
        float: Seconds to wait.
    """
    if background:
        return BACKGROUND_WAIT_S
    return min(FOREGROUND_WAIT_S, state.settings.documents.wait)


def _failure(error: Exception, filing_number: str) -> ServerError:
    """Translate a download or parse failure into an actionable error.

    Args:
        error (Exception): Failure from the document store.
        filing_number (str): Filing being opened.

    Returns:
        ServerError: Error whose message says what to do next.
    """
    for source, target, template in _FAILURES:
        if isinstance(error, source):
            url = dart_viewer_url(filing_number)
            return target(template.format(number=filing_number, url=url, error=error))
    if isinstance(error, OpenDARTError):
        return translate(error)
    url = dart_viewer_url(filing_number)
    return DocumentUnavailableError(
        f"Filing {filing_number} could not be opened ({type(error).__name__}).{_VIEWER.format(url=url)}"
    )


async def load_filing(
    state: AppState, filing_number: str, *, wait_s: float, progress: Progress = no_progress
) -> ParsedFiling:
    """Download and parse a filing, or take it from the cache.

    Args:
        state (AppState): Server state.
        filing_number (str): 14-digit filing number.
        wait_s (float): Longest wait for a download in progress.
        progress (Progress): Receives a message every few seconds while waiting.

    Returns:
        ParsedFiling: The parsed filing.

    Raises:
        InvalidArgumentError: The number is malformed or OpenDART has no such filing.
        StillRunningError: The download outlived the wait; it continues and is cached.
        UpstreamError: The document is unavailable, too large, or unreadable, or the
            download failed and can be retried.
    """
    if not is_filing_number(filing_number):
        message = f"{filing_number!r} is not a filing number. Pass the 14-digit number from search_filings or from a source_filings entry."
        raise InvalidArgumentError(message)
    store = state.require_documents()
    try:
        return await store.get(filing_number, wait_s=wait_s, on_progress=progress)
    except (DocumentError, OpenDARTError, TimeoutError) as error:
        raise _failure(error, filing_number) from error


def _section(info: SectionInfo) -> OutlineSection:
    """Shorten an outline entry for output.

    Args:
        info (SectionInfo): Document-layer outline entry.

    Returns:
        OutlineSection: Entry whose flags appear only when set.
    """
    return OutlineSection(
        id=info.id,
        level=info.level,
        title_en=info.title_en,
        title_ko=info.title_ko,
        chars=info.chars,
        tables=info.tables,
        placeholder=info.placeholder or None,
        image_only=info.image_only or None,
    )


def _document(info: DocumentInfo) -> DocumentEntry:
    """Shorten an archive listing entry for output.

    Args:
        info (DocumentInfo): Document-layer listing entry.

    Returns:
        DocumentEntry: Entry for the outline.
    """
    return DocumentEntry(
        key=info.key,
        form_code=info.form_code,
        name=info.name_en,
        name_ko=info.name_ko,
        chars=info.chars,
    )


def _outline(parsed: ParsedFiling, request: FilingRequest) -> _View:
    """Map a document without its text.

    Args:
        parsed (ParsedFiling): Parsed filing.
        request (FilingRequest): Request.

    Returns:
        _View: Outline, document key, and notes.
    """
    outline = parsed.outline(request.document)
    view = FilingOutline(
        documents=[_document(info) for info in outline.documents],
        sections=[_section(info) for info in outline.sections],
        suggested_sections=outline.suggested_sections,
        amendment=outline.amendment,
    )
    return view, outline.document, outline.notes


def _page(parsed: ParsedFiling, request: FilingRequest) -> _View:
    """Read one page of rendered Markdown.

    Args:
        parsed (ParsedFiling): Parsed filing.
        request (FilingRequest): Request.

    Returns:
        _View: Page, document key, and notes.
    """
    chunk = parsed.read(
        document=request.document,
        section=request.section,
        offset=request.offset,
        max_chars=request.max_chars,
        labels=request.labels,
    )
    view = FilingPage(
        section=_section(chunk.section) if chunk.section else None,
        offset=chunk.offset,
        next_offset=chunk.next_offset,
        total_chars=chunk.total_chars,
        truncated=chunk.truncated,
        content=chunk.content,
    )
    return view, chunk.document, chunk.notes


def _search(parsed: ParsedFiling, request: FilingRequest) -> _View:
    """Find passages matching the query.

    Args:
        parsed (ParsedFiling): Parsed filing.
        request (FilingRequest): Request with a query.

    Returns:
        _View: Hits, document key, and notes.
    """
    query = (request.query or "").strip()
    found = parsed.search(
        query,
        document=request.document,
        section=request.section,
        limit=SEARCH_HITS,
        labels=request.labels,
    )
    view = FilingHits(
        query=query, section=request.section, hits=found.hits, total_hits=found.total_hits
    )
    return view, found.document, found.notes


_VIEWS: Final[dict[str, Callable[[ParsedFiling, FilingRequest], _View]]] = {
    "outline": _outline,
    "read": _page,
    "search": _search,
}


def _section_message(filing_number: str, error: SectionNotFoundError) -> str:
    """Explain an unknown section with the closest outline entries.

    Args:
        filing_number (str): Filing searched.
        error (SectionNotFoundError): The failed lookup.

    Returns:
        str: Message listing up to five sections.
    """
    closest = ", ".join(f"{info.id} ({info.title_en or info.title_ko})" for info in error.closest)
    hint = f" Closest sections: {closest}." if closest else ""
    return f"No section of filing {filing_number} matches {error.query!r}.{hint} Pass an outline ID, an alias, or heading text; mode='outline' lists the sections."


def _navigate(parsed: ParsedFiling, request: FilingRequest) -> _View:
    """Produce the requested view, explaining unknown documents and sections.

    Args:
        parsed (ParsedFiling): Parsed filing.
        request (FilingRequest): Request.

    Returns:
        _View: View, document key, and notes.

    Raises:
        InvalidArgumentError: The document or section does not exist.
    """
    try:
        return _VIEWS[request.mode](parsed, request)
    except UnknownDocumentError as error:
        message = f"Filing {parsed.filing_number} has no document {error.document!r}. Use one of: {", ".join(error.available)}."
        raise InvalidArgumentError(message) from error
    except SectionNotFoundError as error:
        raise InvalidArgumentError(_section_message(parsed.filing_number, error)) from error


def _request_notes(request: FilingRequest) -> list[str]:
    """Check mode-specific arguments and note the ones the mode ignores.

    Args:
        request (FilingRequest): Request.

    Returns:
        list[str]: A note naming ignored arguments, if any.

    Raises:
        InvalidArgumentError: Search mode has no search terms.
    """
    if request.mode == "search" and not (request.query or "").strip():
        message = "mode='search' needs query. Korean terms find body text (전환사채 for convertible bonds); English terms match headings and labels."
        raise InvalidArgumentError(message)
    given = {
        "section": request.section is not None,
        "query": request.query is not None,
        "offset": request.offset != 0,
    }
    allowed = _MODE_ARGUMENTS[request.mode]
    ignored = [name for name, present in given.items() if present and name not in allowed]
    return [f"Ignored in {request.mode} mode: {", ".join(ignored)}."] if ignored else []


def filing_info(parsed: ParsedFiling) -> FilingInfo:
    """Describe a parsed filing.

    Args:
        parsed (ParsedFiling): Parsed filing.

    Returns:
        FilingInfo: Number, form, company, date, amendment flag, format, and viewer link.
    """
    return FilingInfo(
        filing_number=parsed.filing_number,
        form_code=parsed.form_code,
        form_name=parsed.form_name_en,
        form_name_ko=parsed.form_name_ko,
        company=parsed.company_name,
        corp_code=parsed.corp_code,
        filed=filing_date(parsed.filing_number),
        is_amendment=parsed.amendment is not None,
        format=parsed.format,
        dart_url=dart_viewer_url(parsed.filing_number),
    )


async def open_filing(
    state: AppState, request: FilingRequest, *, wait_s: float, progress: Progress = no_progress
) -> ReadFilingResult:
    """Show a filing's outline, one page of its text, or passages matching a query.

    Args:
        state (AppState): Server state.
        request (FilingRequest): What to show.
        wait_s (float): Longest wait for the download.
        progress (Progress): Receives messages while the download runs.

    Returns:
        ReadFilingResult: The filing and the requested view.
    """
    notes = _request_notes(request)
    parsed = await load_filing(state, request.filing_number, wait_s=wait_s, progress=progress)
    # A first Korean or bilingual rendering of a large filing is CPU-bound.
    view, document, view_notes = await anyio.to_thread.run_sync(_navigate, parsed, request)
    title = parsed.form_name_en or parsed.form_name_ko
    return ReadFilingResult(
        filing=filing_info(parsed),
        mode=request.mode,
        document=document,
        outline=view if isinstance(view, FilingOutline) else None,
        page=view if isinstance(view, FilingPage) else None,
        search=view if isinstance(view, FilingHits) else None,
        source_filings=[SourceFiling.of(parsed.filing_number, title)],
        notes=[*notes, *view_notes],
        as_of=state.today(),
    )


async def filing_outline(state: AppState, filing_number: str) -> ReadFilingResult:
    """Outline a filing's main document, for the filing resource.

    Args:
        state (AppState): Server state.
        filing_number (str): 14-digit filing number.

    Returns:
        ReadFilingResult: The outline result.
    """
    wait_s = wait_seconds(state, background=False)
    return await open_filing(state, FilingRequest(filing_number), wait_s=wait_s)


async def filing_section(state: AppState, filing_number: str, section_id: str) -> str:
    """Render one section of a filing's main document, unpaged, for the section resource.

    Args:
        state (AppState): Server state.
        filing_number (str): 14-digit filing number.
        section_id (str): Outline ID, alias, or heading text.

    Returns:
        str: Markdown of the section and its subsections.

    Raises:
        InvalidArgumentError: No section matches.
    """
    wait_s = wait_seconds(state, background=False)
    parsed = await load_filing(state, filing_number, wait_s=wait_s)
    try:
        return parsed.section_markdown(section_id)
    except SectionNotFoundError as error:
        raise InvalidArgumentError(_section_message(filing_number, error)) from error
