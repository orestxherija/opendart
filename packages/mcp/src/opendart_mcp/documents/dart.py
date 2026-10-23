"""DART XML builder: sections, headings, cover and amendment containers, and metadata.

DART documents nest ``SECTION-1`` to ``SECTION-n`` containers (often inside transparent
``LIBRARY`` blocks), each headed by a ``TITLE``. Periodic reports also place table-of-contents
headings directly inside a container (financial statements and each note), so a ``TITLE`` with
``ATOC="Y"`` that is not its container's first heading opens a subsection that runs until the
next such heading or the end of the container. Other loose headings render as subheadings.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, override

from opendart_mcp.documents.building import SectionBuilder
from opendart_mcp.documents.markup import MarkupBuilder
from opendart_mcp.documents.tree import DocumentTree, Label, Subheading, collapse, compact

if TYPE_CHECKING:
    from opendart_mcp.documents.building import Attributes, Frame
    from opendart_mcp.documents.tree import SectionKind

_SECTION_TAG = re.compile(r"section-\d+")
_CONTAINER_KINDS: dict[str, SectionKind] = {"cover": "cover", "correction": "correction"}
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9._~-]+")
_TABLE_OF_CONTENTS = "목차"
# Live filings nest at most three levels; deeper headings render as subheadings.
MAX_SECTION_DEPTH = 12


class DartBuilder(MarkupBuilder):
    """Build a document tree from one DART XML member.

    Attributes:
        form_code (str | None): ``DOCUMENT-NAME ACODE``.
        form_name (str | None): ``DOCUMENT-NAME`` text.
        company_name (str | None): ``COMPANY-NAME`` text.
        corp_code (str | None): ``COMPANY-NAME AREGCIK``.
        cover_title_en (str | None): ``COVER-TITLE ENG``.
    """

    SKIP_TAGS: frozenset[str] = frozenset(
        {"summary", "formula-version", "colgroup", "style", "script"}
    )

    def __init__(self) -> None:
        """Start an empty DART document."""
        super().__init__()
        self.form_code: str | None = None
        self.form_name: str | None = None
        self.company_name: str | None = None
        self.corp_code: str | None = None
        self.cover_title_en: str | None = None
        self._ids: set[str] = set()

    @override
    def hook_name(self, tag: str) -> str:
        """Group section containers and headings under shared hooks.

        Args:
            tag (str): Lowercased tag name.

        Returns:
            str: ``container``, ``title``, or the base hook name.
        """
        if tag in _CONTAINER_KINDS or _SECTION_TAG.fullmatch(tag):
            return "container"
        if tag in {"title", "cover-title"}:
            return "title"
        return super().hook_name(tag)

    @override
    def handle_data(self, data: str) -> None:
        """Ignore text outside every element, such as the tail of a DOCTYPE internal subset.

        Args:
            data (str): Text with character references decoded.
        """
        if self.frames:
            super().handle_data(data)

    def build(self) -> DocumentTree:
        """Finish parsing and return the document tree.

        Returns:
            DocumentTree: The parsed document.
        """
        items = tuple(self.finish_items())
        return DocumentTree(
            format="dart_xml",
            items=items,
            form_code=self.form_code,
            form_name_ko=self.form_name,
            company_name=self.company_name,
            corp_code=self.corp_code,
            cover_title_en=self.cover_title_en,
        )

    # Sections -------------------------------------------------------------------------------

    def _start_container(self, frame: Frame, attrs: Attributes) -> None:
        """Start a section container; its section opens at its first heading.

        Args:
            frame (Frame): Frame for the opening container element.
            attrs (Attributes): Attributes of the container element.
        """
        del frame, attrs
        self.flush()

    def _end_container(self, frame: Frame) -> None:
        """Close a container's section and any subsections opened inside it.

        Args:
            frame (Frame): Frame for the closing container element.
        """
        self.flush()
        del self.open_sections[frame.sections :]

    def _start_title(self, frame: Frame, attrs: Attributes) -> None:
        """Start capturing a heading.

        Args:
            frame (Frame): Frame for the heading element.
            attrs (Attributes): Heading attributes used when the text is placed.
        """
        self.flush()
        frame.attrs = attrs
        self.capture = []

    def _end_title(self, frame: Frame) -> None:
        """Place a captured heading as a section or a subheading.

        Args:
            frame (Frame): Frame holding the heading tag and attributes.
        """
        text = collapse("".join(self.capture or ()))
        self.capture = None
        attrs = frame.attrs or {}
        if not text:
            return
        label = Label(text, collapse(attrs.get("eng") or "") or None)
        if frame.tag == "cover-title" and label.en:
            self.cover_title_en = self.cover_title_en or label.en
        self.place_heading(label, attrs)

    def place_heading(self, label: Label, attrs: Attributes) -> None:
        """Open a container section, a table-of-contents subsection, or emit a subheading.

        Args:
            label (Label): Heading text.
            attrs (Attributes): ``TITLE`` attributes.
        """
        container = self.container()
        if container is not None and not container.titled:
            container.titled = True
            del self.open_sections[container.sections :]
            self.open_section(label, attrs, _CONTAINER_KINDS.get(container.tag, "section"))
        elif (attrs.get("atoc") or "").strip().upper() == "Y":
            keep = 0 if container is None else container.sections + 1
            del self.open_sections[keep:]
            self.open_section(label, attrs, "section")
        elif compact(label.ko) != _TABLE_OF_CONTENTS:
            self.emit(Subheading(label))

    def container(self) -> Frame | None:
        """Return the innermost open section container.

        Returns:
            Frame | None: Its frame, or None outside any container.
        """
        for frame in reversed(self.frames):
            if self.hook_name(frame.tag) == "container":
                return frame
        return None

    def open_section(self, label: Label, attrs: Attributes, kind: SectionKind) -> None:
        """Create a section under the current one and make it current.

        Beyond the maximum depth the heading becomes a subheading instead, which keeps the
        recursive tree helpers within Python's recursion limit.

        Args:
            label (Label): Heading.
            attrs (Attributes): ``TITLE`` attributes with the code and TOC ID.
            kind (SectionKind): Container kind.
        """
        parent = self.current()
        if parent.level >= MAX_SECTION_DEPTH:
            self.emit(Subheading(label))
            return
        parent.children += 1
        path = (*parent.path, parent.children)
        code = _clean_code(attrs.get("aassocnote"))
        section = SectionBuilder(
            id=self.unique_id(code or _toc_id(attrs.get("atocid")) or _ordinal_id(path)),
            level=parent.level + 1,
            title=label,
            code=code,
            kind=kind,
            parent_id=parent.id or None,
            path=path,
        )
        parent.items.append(section)
        self.open_sections.append(section)

    def unique_id(self, candidate: str) -> str:
        """Make a section ID unique within the document.

        Args:
            candidate (str): Preferred ID.

        Returns:
            str: The candidate, or the candidate with a ``~N`` suffix when already used.
        """
        unique, counter = candidate, 1
        while unique in self._ids:
            counter += 1
            unique = f"{candidate}~{counter}"
        self._ids.add(unique)
        return unique

    # Metadata -------------------------------------------------------------------------------

    def _start_document_name(self, frame: Frame, attrs: Attributes) -> None:
        """Capture the form name and code.

        Args:
            frame (Frame): Frame that stores the document-name attributes.
            attrs (Attributes): Attributes containing the form code.
        """
        frame.attrs = attrs
        self.capture = []

    def _end_document_name(self, frame: Frame) -> None:
        """Record the form name and code.

        Args:
            frame (Frame): Frame containing the captured form code.
        """
        self.form_name = collapse("".join(self.capture or ())) or None
        self.form_code = collapse((frame.attrs or {}).get("acode") or "") or None
        self.capture = None

    def _start_company_name(self, frame: Frame, attrs: Attributes) -> None:
        """Capture the company name and corporation code.

        Args:
            frame (Frame): Frame that stores the company-name attributes.
            attrs (Attributes): Attributes containing the corporation code.
        """
        frame.attrs = attrs
        self.capture = []

    def _end_company_name(self, frame: Frame) -> None:
        """Record the company name and corporation code.

        Args:
            frame (Frame): Frame containing the captured corporation code.
        """
        self.company_name = collapse("".join(self.capture or ())) or None
        self.corp_code = collapse((frame.attrs or {}).get("aregcik") or "") or None
        self.capture = None

    # Images ---------------------------------------------------------------------------------

    def _start_image(self, frame: Frame, attrs: Attributes) -> None:
        """Start collecting an image's filename and caption.

        Args:
            frame (Frame): Frame tracking the image element.
            attrs (Attributes): Image attributes; currently unused.
        """
        del attrs
        frame.titled = self.image_parts is None
        if frame.titled:
            self.image_parts = {}

    def _end_image(self, frame: Frame) -> None:
        """Place the collected image reference.

        Args:
            frame (Frame): Frame indicating whether this image wrapper owns the caption.
        """
        if not frame.titled or self.image_parts is None:
            return
        parts, self.image_parts = self.image_parts, None
        caption = collapse("".join(parts.get("img-caption", ())))
        self.place_image(caption or collapse("".join(parts.get("img", ()))))

    def _start_img(self, frame: Frame, attrs: Attributes) -> None:
        """Collect a filename for an ``IMG`` outside an ``IMAGE`` wrapper.

        Args:
            frame (Frame): Frame tracking the ``IMG`` element.
            attrs (Attributes): Image attributes passed to the shared image handler.
        """
        self._start_image(frame, attrs)

    def _end_img(self, frame: Frame) -> None:
        """Place an ``IMG`` reference outside an ``IMAGE`` wrapper.

        Args:
            frame (Frame): Frame tracking the ``IMG`` element.
        """
        self._end_image(frame)


def _clean_code(value: str | None) -> str | None:
    """Turn an ``AASSOCNOTE`` value into a URI-safe section code.

    Args:
        value (str | None): Attribute value.

    Returns:
        str | None: The code, or None when blank.
    """
    code = _UNSAFE_ID.sub("_", (value or "").strip()).strip("_")
    return code or None


def _toc_id(value: str | None) -> str | None:
    """Build an ``s{ATOCID}`` section ID.

    Args:
        value (str | None): ``ATOCID`` attribute value.

    Returns:
        str | None: The ID, or None when the attribute is not a number.
    """
    digits = (value or "").strip()
    return f"s{digits}" if digits.isdigit() else None


def _ordinal_id(path: tuple[int, ...]) -> str:
    """Build an ordinal-path section ID such as ``p2.1.3``.

    Args:
        path (tuple[int, ...]): 1-based positions from the root.

    Returns:
        str: The ID.
    """
    return "p" + ".".join(str(index) for index in path)
