"""Outline entries, placeholder detection, and document-level notes.

Semi-annual and quarterly reports keep the MD&A headings with a one-line omission statement
(``...본 항목을 기재하지 않습니다``); such sections, and sections that only say "not applicable",
are marked as placeholders. Sections whose content is only images the archive omits are
marked as image-only.
"""

from __future__ import annotations

import bisect
import re
from typing import TYPE_CHECKING

from opendart_analysis.documents.forms import ANNUAL_REPORT, INTERIM_FORMS, dart_url
from opendart_analysis.documents.models import SectionInfo
from opendart_analysis.documents.tree import Image, Paragraph, Section, Subheading, Table

if TYPE_CHECKING:
    from opendart_analysis.documents.render import Rendering
    from opendart_analysis.documents.tree import DocumentTree

_OMISSION = re.compile(
    r"기재\s*하지\s*(?:않|아니)|기재\s*(?:를|을)?\s*생략|생략\s*(?:합니다|하였습니다|함)|작성\s*하지\s*않|해당\s*사항\s*(?:이|은)?\s*없|해당\s*없음"
)
_PLACEHOLDER_MAX_CHARS = 300
_MAX_LISTED = 10
_MDNA_PREFIX = "D-0-4"
_ANNUAL_NOTE = "The API archive omits attachments the DART website shows for annual reports, typically the articles of incorporation, internal accounting control report, business report to shareholders, audit committee's audit report, audit committee opinion on internal monitoring, and treasury stock report; view them at {url}."
_MDNA_NOTE = "MD&A sections (D-0-4-*) only carry an omission statement in semi-annual and quarterly reports; the full MD&A is in the annual report."


def section_infos(sections: list[Section], rendering: Rendering) -> list[SectionInfo]:
    """Build outline entries from a document's sections and its English rendering.

    Args:
        sections (list[Section]): Sections in document order.
        rendering (Rendering): The document rendered with English labels.

    Returns:
        list[SectionInfo]: One entry per section, in document order.
    """
    flags = _flags(sections)
    starts = [table.start for table in rendering.tables]
    infos: list[SectionInfo] = []
    for section in sections:
        start, end = rendering.spans[section.id]
        placeholder, image_only = flags[section.id]
        infos.append(
            SectionInfo(
                id=section.id,
                level=section.level,
                title_en=section.title.en,
                title_ko=section.title.ko,
                chars=end - start,
                tables=bisect.bisect_left(starts, end) - bisect.bisect_left(starts, start),
                placeholder=placeholder,
                image_only=image_only,
                parent_id=section.parent_id,
            )
        )
    return infos


def _flags(sections: list[Section]) -> dict[str, tuple[bool, bool]]:
    """Compute (placeholder, image_only) for every section, children before parents.

    A placeholder states in a paragraph that the item is omitted or not applicable, and has
    little other text; a cover field such as "relief: N/A" does not count.

    Args:
        sections (list[Section]): Sections in document order.

    Returns:
        dict[str, tuple[bool, bool]]: Flags by section ID.
    """
    flags: dict[str, tuple[bool, bool]] = {}
    for section in reversed(sections):
        prose, cells, images = own_content(section)
        children = [flags[item.id][0] for item in section.items if isinstance(item, Section)]
        if prose or cells:
            short = len(prose) + len(cells) <= _PLACEHOLDER_MAX_CHARS
            placeholder = short and bool(_OMISSION.search(prose)) and all(children)
        else:
            placeholder = bool(children) and not images and all(children)
        flags[section.id] = (placeholder, images > 0 and not prose and not cells)
    return flags


def own_content(section: Section) -> tuple[str, str, int]:
    """Collect a section's own prose and table text (excluding subsections) and count images.

    Args:
        section (Section): Section to inspect.

    Returns:
        tuple[str, str, int]: Paragraph and subheading text, table cell text (both Korean,
            joined with spaces), and the number of images.
    """
    prose: list[str] = []
    cells: list[str] = []
    images = 0
    for item in section.items:
        if isinstance(item, Paragraph):
            prose.append(item.plain)
        elif isinstance(item, Subheading):
            prose.append(item.label.ko)
        elif isinstance(item, Table):
            cells.extend(cell.label.ko for row in item.rows for cell in row if cell.label.ko)
        elif isinstance(item, Image):
            images += 1
    return " ".join(prose).strip(), " ".join(cells).strip(), images


def document_notes(
    tree: DocumentTree, *, key: str, filing_number: str, infos: list[SectionInfo]
) -> list[str]:
    """List caveats for one document's outline.

    Args:
        tree (DocumentTree): Parsed document.
        key (str): Document key.
        filing_number (str): 14-digit filing number.
        infos (list[SectionInfo]): The document's outline entries.

    Returns:
        list[str]: Notes about omitted attachments, image-only sections, and placeholders.
    """
    notes: list[str] = []
    if key == "main" and tree.form_code == ANNUAL_REPORT:
        notes.append(_ANNUAL_NOTE.format(url=dart_url(filing_number)))
    images = [info.id for info in infos if info.image_only]
    if images:
        listed = ", ".join(images[:_MAX_LISTED]) + (", ..." if len(images) > _MAX_LISTED else "")
        notes.append(f"Sections {listed} contain only images, which the archive does not include.")
    mdna = [info for info in infos if info.id.startswith(_MDNA_PREFIX) and info.placeholder]
    if tree.form_code in INTERIM_FORMS and mdna:
        notes.append(_MDNA_NOTE)
    return notes
