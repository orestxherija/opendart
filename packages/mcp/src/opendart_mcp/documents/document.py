"""One parsed document of a filing archive, with its outline and memoized renderings.

The English rendering is built eagerly, because outlines report its character counts; Korean
and bilingual renderings are built on first use and kept with the document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_mcp.documents.aliases import ALIASES, alias_sections
from opendart_mcp.documents.forms import PERIODIC_FORMS, english_form_name
from opendart_mcp.documents.models import DocumentInfo, SuggestedSection
from opendart_mcp.documents.outline import document_notes, section_infos
from opendart_mcp.documents.render import Rendering, render
from opendart_mcp.documents.tree import walk_sections

if TYPE_CHECKING:
    from opendart_mcp.documents.archive import Member
    from opendart_mcp.documents.models import LabelMode, SectionInfo
    from opendart_mcp.documents.tree import DocumentTree, Section

_EMPTY = Rendering("", {}, (), (0,), (None,))


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """A document of the archive with its outline and renderings.

    Attributes:
        info (DocumentInfo): Archive listing entry.
        tree (DocumentTree | None): Parsed content, or None for members that are not markup.
        sections (tuple[Section, ...]): Sections in document order.
        infos (tuple[SectionInfo, ...]): Outline entries, aligned with ``sections``.
        notes (tuple[str, ...]): Outline caveats.
        suggested (tuple[SuggestedSection, ...]): Aliases present (periodic reports only).
        renders (dict[LabelMode, Rendering]): Renderings built so far, by label language.
    """

    info: DocumentInfo
    tree: DocumentTree | None
    sections: tuple[Section, ...]
    infos: tuple[SectionInfo, ...]
    notes: tuple[str, ...]
    suggested: tuple[SuggestedSection, ...]
    renders: dict[LabelMode, Rendering]

    @property
    def periodic(self) -> bool:
        """Report whether the document is an annual, semi-annual, or quarterly report.

        Returns:
            bool: True for periodic-report form codes.
        """
        return (self.info.form_code or "") in PERIODIC_FORMS

    def rendering(self, mode: LabelMode) -> Rendering:
        """Return the rendering in a label language, building it on first use.

        Args:
            mode (LabelMode): Label language.

        Returns:
            Rendering: The rendering; empty for members that are not markup.
        """
        cached = self.renders.get(mode)
        if cached is not None:
            return cached
        if self.tree is None:
            return _EMPTY
        return self.renders.setdefault(mode, render(self.tree, mode))

    def info_for(self, section_id: str) -> SectionInfo:
        """Return the outline entry of a section.

        Args:
            section_id (str): Section ID.

        Returns:
            SectionInfo: The entry.

        Raises:
            KeyError: The document has no such section.
        """
        for info in self.infos:
            if info.id == section_id:
                return info
        raise KeyError(section_id)

    @property
    def rendered_chars(self) -> int:
        """Count the characters held by this document's renderings.

        Returns:
            int: Total rendered characters.
        """
        return sum(len(rendering.text) for rendering in tuple(self.renders.values()))


def build_document(
    tree: DocumentTree, member: Member, *, key: str, filing_number: str
) -> ParsedDocument:
    """Render a parsed member in English and build its outline.

    Args:
        tree (DocumentTree): Parsed member.
        member (Member): The archive member.
        key (str): Document key.
        filing_number (str): 14-digit filing number.

    Returns:
        ParsedDocument: The document.
    """
    english = render(tree, "english")
    sections = walk_sections(tree.items)
    infos = section_infos(sections, english)
    info = DocumentInfo(
        key=key,
        form_code=tree.form_code,
        name_en=english_form_name(tree),
        name_ko=tree.form_name_ko,
        chars=len(english.text),
        member=member.name,
        size_bytes=member.size,
    )
    periodic = (tree.form_code or "") in PERIODIC_FORMS
    return ParsedDocument(
        info=info,
        tree=tree,
        sections=tuple(sections),
        infos=tuple(infos),
        notes=tuple(document_notes(tree, key=key, filing_number=filing_number, infos=infos)),
        suggested=tuple(_suggested(sections)) if periodic else (),
        renders={"english": english},
    )


def unrendered_document(member: Member, key: str) -> ParsedDocument:
    """List a member that is neither DART XML nor KRX HTML without rendering it.

    Args:
        member (Member): The archive member.
        key (str): Document key.

    Returns:
        ParsedDocument: A document with no content.
    """
    info = DocumentInfo(
        key=key, chars=0, member=member.name, size_bytes=member.size, rendered=False
    )
    note = (
        f"Member {member.name} ({member.size:,} bytes) is not DART XML or KRX HTML; not rendered."
    )
    return ParsedDocument(info, None, (), (), (note,), (), {})


def _suggested(sections: list[Section]) -> list[SuggestedSection]:
    """List the periodic-report aliases a document supports.

    Args:
        sections (list[Section]): Sections in document order.

    Returns:
        list[SuggestedSection]: Aliases that resolve, in alias-table order.
    """
    suggested: list[SuggestedSection] = []
    for alias in ALIASES:
        found = alias_sections(alias, sections, periodic=True)
        if found:
            ids = [section.id for section in found]
            suggested.append(
                SuggestedSection(alias=alias.name, section_ids=ids, title_en=found[0].title.en)
            )
    return suggested
