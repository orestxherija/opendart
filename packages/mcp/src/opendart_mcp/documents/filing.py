"""Parse a filing archive and navigate it: outline, paged reads, search, and sections.

:func:`parse_filing` is synchronous and CPU-bound; callers run it in a worker thread. The
resulting :class:`ParsedFiling` is immutable apart from memoized renderings, so it can be
cached and shared between requests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, get_args

from opendart_mcp.documents.aliases import closest, find_sections
from opendart_mcp.documents.amendment import extract_amendment
from opendart_mcp.documents.archive import read_members
from opendart_mcp.documents.document import build_document, unrendered_document
from opendart_mcp.documents.errors import (
    MalformedArchiveError,
    SectionNotFoundError,
    UnknownDocumentError,
)
from opendart_mcp.documents.forms import dart_url, document_keys
from opendart_mcp.documents.models import (
    LabelMode,
    Outline,
    ReadChunk,
    SearchHit,
    SearchResult,
)
from opendart_mcp.documents.paging import Scope, read_page
from opendart_mcp.documents.parsing import parse_markup, sniff_format
from opendart_mcp.documents.search import search_text

if TYPE_CHECKING:
    from opendart_mcp.documents.archive import ArchiveLimits
    from opendart_mcp.documents.document import ParsedDocument
    from opendart_mcp.documents.models import (
        DocumentFormat,
        SectionInfo,
    )
    from opendart_mcp.documents.render import Rendering
    from opendart_mcp.documents.search import Match
    from opendart_mcp.documents.tree import DocumentTree, Section

DEFAULT_MAX_CHARS = 8000
MAX_CHARS_CAP = 30_000
MAX_HITS = 50
_LABELS: tuple[str, ...] = get_args(LabelMode)


class ParsedFiling:
    """A parsed filing archive.

    Attributes:
        filing_number (str): 14-digit filing number.
        format (DocumentFormat): ``dart_xml`` or ``krx_html`` (of the main document).
        form_code (str | None): DART form code of the main document.
        form_name_en (str | None): English form name, when known.
        form_name_ko (str | None): Korean form name.
        title (str | None): KRX page title; for DART documents, the Korean form name.
        company_name (str | None): Korean company name from the document.
        corp_code (str | None): DART corporation code from the document (DART only).
        documents (list[DocumentInfo]): Documents in the archive, main first.
        amendment (Amendment | None): Correction summary for amended filings.
        dart_url (str): English DART viewer link.
    """

    def __init__(self, filing_number: str, documents: list[ParsedDocument]) -> None:
        """Assemble a parsed filing from its documents; the first is the main document.

        Args:
            filing_number (str): 14-digit filing number.
            documents (list[ParsedDocument]): Parsed documents, main first.
        """
        main = documents[0]
        tree = main.tree
        self.filing_number = filing_number
        self.format: DocumentFormat = tree.format if tree is not None else "dart_xml"
        self.form_code = main.info.form_code
        self.form_name_en = main.info.name_en
        self.form_name_ko = main.info.name_ko
        self.title = (tree.title or tree.form_name_ko) if tree is not None else None
        self.company_name = tree.company_name if tree is not None else None
        self.corp_code = tree.corp_code if tree is not None else None
        self.documents = [document.info for document in documents]
        self.amendment = extract_amendment(tree) if tree is not None else None
        self.dart_url = dart_url(filing_number)
        self._documents = {document.info.key: document for document in documents}

    @property
    def rendered_chars(self) -> int:
        """Count rendered characters held by this filing, for cache sizing.

        Returns:
            int: Characters across all renderings built so far.
        """
        return sum(document.rendered_chars for document in self._documents.values())

    def tree(self, document: str = "main") -> DocumentTree | None:
        """Return a document's parsed tree, for extractors in this package.

        Args:
            document (str): Document key, form code, or member name.

        Returns:
            DocumentTree | None: The tree, or None for a member that is not markup.

        Raises:
            UnknownDocumentError: The archive has no such document.
        """
        return self._document(document).tree

    def outline(self, document: str = "main") -> Outline:
        """Map a document without its body text.

        Args:
            document (str): Document key, form code, or member name.

        Returns:
            Outline: Documents, sections, aliases, amendment summary, and notes.

        Raises:
            UnknownDocumentError: The archive has no such document.
        """
        parsed = self._document(document)
        main = parsed.info.key == self.documents[0].key
        notes = list(parsed.notes)
        if main and self.amendment is not None:
            section = self.amendment.section_id
            notes.append(
                f"This filing corrects an earlier one; `amendment` summarizes the changes and section {section} has the full text."
            )
        return Outline(
            filing_number=self.filing_number,
            document=parsed.info.key,
            documents=self.documents,
            sections=list(parsed.infos),
            suggested_sections=list(parsed.suggested),
            amendment=self.amendment if main else None,
            notes=notes,
        )

    def read(
        self,
        *,
        document: str = "main",
        section: str | None = None,
        offset: int = 0,
        max_chars: int = DEFAULT_MAX_CHARS,
        labels: LabelMode = "english",
    ) -> ReadChunk:
        """Read rendered Markdown of a section or the whole document, one page at a time.

        Args:
            document (str): Document key, form code, or member name.
            section (str | None): Outline ID, alias, or heading text; None reads everything.
            offset (int): Character offset within the section or document.
            max_chars (int): Page size, capped at 30,000 characters.
            labels (LabelMode): Label language.

        Returns:
            ReadChunk: The page, its typed tables, and the next offset.

        Raises:
            ValueError: ``offset`` is negative, ``max_chars`` is below 1, or ``labels`` is
                unknown.
            UnknownDocumentError: The archive has no such document.
            SectionNotFoundError: No section matches ``section``.
        """
        mode = _check_labels(labels)
        if offset < 0 or max_chars < 1:
            msg = "offset must be >= 0 and max_chars >= 1"
            raise ValueError(msg)
        parsed = self._document(document)
        rendering = parsed.rendering(mode)
        scope, sections, notes = self._scope(parsed, rendering, section)
        if max_chars > MAX_CHARS_CAP:
            notes.append(f"max_chars was capped at {MAX_CHARS_CAP:,}.")
        info = parsed.info_for(sections[0].id) if sections else None
        notes.extend(_section_notes(info))
        past_end = offset >= scope.length
        if past_end:
            notes.append(f"offset {offset:,} is past the end ({scope.length:,} characters).")
        empty = ReadChunk(
            filing_number=self.filing_number,
            document=parsed.info.key,
            section=info,
            offset=offset,
            total_chars=scope.length,
            truncated=False,
            content="",
            labels=mode,
            notes=notes,
        )
        if past_end:
            return empty
        page = read_page(rendering, scope, (offset, min(max_chars, MAX_CHARS_CAP)), mode=mode)
        following = page.end if page.end < scope.length else None
        return empty.model_copy(
            update={
                "offset": page.start,
                "next_offset": following,
                "truncated": following is not None,
                "content": page.content,
                "tables": page.tables,
                "notes": notes + page.notes,
            }
        )

    def search(
        self,
        query: str,
        *,
        document: str = "main",
        section: str | None = None,
        limit: int = 20,
        labels: LabelMode = "english",
    ) -> SearchResult:
        """Find passages matching a query.

        Korean terms match body text; English terms match the filing's English headings and
        labels. Hit offsets refer to the searched scope in the given label language.

        Args:
            query (str): Search terms.
            document (str): Document key, form code, or member name.
            section (str | None): Outline ID, alias, or heading text to search within.
            limit (int): Most hits to return, at most 50.
            labels (LabelMode): Label language of the searched rendering.

        Returns:
            SearchResult: Hits with about 300 characters of context each.

        Raises:
            ValueError: ``query`` is blank, ``limit`` is below 1, or ``labels`` is unknown.
            UnknownDocumentError: The archive has no such document.
            SectionNotFoundError: No section matches ``section``.
        """
        mode = _check_labels(labels)
        if limit < 1:
            msg = "limit must be >= 1"
            raise ValueError(msg)
        parsed = self._document(document)
        rendering = parsed.rendering(mode)
        scope, _, notes = self._scope(parsed, rendering, section)
        found = search_text(scope.text(rendering.text), query, min(limit, MAX_HITS))
        hits = [_hit(parsed, rendering, scope=scope, match=match) for match in found.matches]
        if not found.exact:
            notes.append("No exact match for the phrase; showing matches for its words.")
        if found.limited:
            notes.append(
                f"Showing {len(hits)} of {found.total} matches; narrow the query or section."
            )
        return SearchResult(
            filing_number=self.filing_number,
            document=parsed.info.key,
            section=section,
            query=query,
            hits=hits,
            total_hits=found.total,
            notes=notes,
        )

    def section_markdown(
        self, section_id: str, *, document: str = "main", labels: LabelMode = "english"
    ) -> str:
        """Render one section (or an alias's sections) as Markdown, unpaged.

        Args:
            section_id (str): Outline ID, alias, or heading text.
            document (str): Document key, form code, or member name.
            labels (LabelMode): Label language.

        Returns:
            str: The section's Markdown, including subsections.

        Raises:
            ValueError: ``labels`` is unknown.
            UnknownDocumentError: The archive has no such document.
            SectionNotFoundError: No section matches ``section_id``.
        """
        parsed = self._document(document)
        rendering = parsed.rendering(_check_labels(labels))
        scope, _, _ = self._scope(parsed, rendering, section_id)
        return scope.text(rendering.text)

    def resolve_section(self, query: str, document: str = "main") -> SectionInfo:
        """Resolve an outline ID, alias, or heading substring to a section.

        Args:
            query (str): Section query.
            document (str): Document key, form code, or member name.

        Returns:
            SectionInfo: The first matching section.

        Raises:
            UnknownDocumentError: The archive has no such document.
            SectionNotFoundError: No section matches; carries the closest entries.
        """
        parsed = self._document(document)
        return parsed.info_for(self._sections(parsed, query)[0].id)

    def _document(self, document: str) -> ParsedDocument:
        """Find a document by key, form code, or member name.

        Args:
            document (str): Requested document.

        Returns:
            ParsedDocument: The document.

        Raises:
            UnknownDocumentError: No document matches.
        """
        wanted = document.strip()
        found = self._documents.get(wanted)
        if found is None:
            found = next(
                (
                    d
                    for d in self._documents.values()
                    if wanted in {d.info.form_code, d.info.member}
                ),
                None,
            )
        if found is None:
            raise UnknownDocumentError(list(self._documents), document=document)
        return found

    def _sections(self, parsed: ParsedDocument, query: str) -> list[Section]:
        """Resolve a section query or raise with the closest outline entries.

        Args:
            parsed (ParsedDocument): Document to search.
            query (str): Section query.

        Returns:
            list[Section]: Matching sections in reading order.

        Raises:
            SectionNotFoundError: Nothing matches.
        """
        found = find_sections(query, list(parsed.sections), periodic=parsed.periodic)
        if not found:
            raise SectionNotFoundError(query, closest(query, parsed.infos))
        return found

    def _scope(
        self, parsed: ParsedDocument, rendering: Rendering, section: str | None
    ) -> tuple[Scope, list[Section], list[str]]:
        """Resolve what to read: the whole document or the matching sections.

        Args:
            parsed (ParsedDocument): Document to read.
            rendering (Rendering): Its rendering in the requested labels.
            section (str | None): Section query, or None for the whole document.

        Returns:
            tuple[Scope, list[Section], list[str]]: The scope, its sections, and notes.
        """
        if section is None:
            notes = list(parsed.notes[:1]) if parsed.tree is None else []
            return Scope.of([(0, len(rendering.text))]), [], notes
        sections = self._sections(parsed, section)
        notes = []
        if len(sections) > 1:
            notes.append(f"{section!r} covers sections {", ".join(s.id for s in sections)}.")
        return Scope.of([rendering.spans[s.id] for s in sections]), sections, notes


def parse_filing(
    filing_number: str, archive: bytes, *, limits: ArchiveLimits | None = None
) -> ParsedFiling:
    """Unpack and parse a filing archive from ``disclosures.document``.

    Args:
        filing_number (str): 14-digit filing number.
        archive (bytes): ZIP archive bytes.
        limits (ArchiveLimits | None): Archive limits. None uses the defaults.

    Returns:
        ParsedFiling: The parsed filing.

    Raises:
        ArchiveTooLargeError: The archive exceeds a size limit.
        MalformedArchiveError: The archive is unreadable or holds no DART XML or KRX HTML.
    """
    members = read_members(archive, limits)
    formats = [sniff_format(member.data) for member in members]
    if not any(formats):
        msg = "The archive holds no DART XML or KRX HTML document"
        raise MalformedArchiveError(msg)
    keys = document_keys([member.name for member in members], formats, filing_number)
    documents: list[ParsedDocument] = []
    for member, document_format, key in zip(members, formats, keys, strict=True):
        if document_format is None:
            documents.append(unrendered_document(member, key))
        else:
            tree = parse_markup(member.data, document_format)
            documents.append(build_document(tree, member, key=key, filing_number=filing_number))
    main = next(document for document in documents if document.info.key == "main")
    return ParsedFiling(filing_number, [main, *(d for d in documents if d is not main)])


def _check_labels(labels: str) -> LabelMode:
    """Validate a label language.

    Args:
        labels (str): Requested label language.

    Returns:
        LabelMode: The validated value.

    Raises:
        ValueError: The value is not english, korean, or both.
    """
    if labels not in _LABELS:
        msg = f"labels must be one of {", ".join(_LABELS)}"
        raise ValueError(msg)
    return cast("LabelMode", labels)


def _section_notes(info: SectionInfo | None) -> list[str]:
    """Explain placeholder and image-only sections.

    Args:
        info (SectionInfo | None): Section being read.

    Returns:
        list[str]: Notes, possibly empty.
    """
    if info is None:
        return []
    if info.placeholder:
        return ["This section only states that the item is omitted or not applicable."]
    if info.image_only:
        return ["This section holds only images, which the archive does not include."]
    return []


def _hit(parsed: ParsedDocument, rendering: Rendering, *, scope: Scope, match: Match) -> SearchHit:
    """Describe one search hit with the section that contains the match.

    Args:
        parsed (ParsedDocument): Searched document.
        rendering (Rendering): Searched rendering.
        scope (Scope): Searched scope.
        match (Match): The match and its snippet.

    Returns:
        SearchHit: The hit.
    """
    section_id = rendering.owner(scope.absolute(match.position))
    span = rendering.spans.get(section_id) if section_id else None
    info = parsed.info_for(section_id) if section_id else None
    return SearchHit(
        section_id=section_id,
        section_title_en=(info.title_en or info.title_ko) if info else None,
        offset=match.offset,
        section_offset=max(scope.absolute(match.offset) - span[0], 0) if span else None,
        snippet=match.snippet,
    )
