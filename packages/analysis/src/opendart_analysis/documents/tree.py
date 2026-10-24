"""Immutable internal model of a parsed filing document: sections, blocks, and tables.

Both DART XML and KRX HTML parse into this model. Labels keep the Korean text with the English
``ENG`` attribute where the filing supplies one, so any label language can be rendered later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from opendart_analysis.documents.models import DocumentFormat, LabelMode

type SectionKind = Literal["section", "cover", "correction", "body"]

_SPACES = re.compile(r"\s+")


def collapse(text: str) -> str:
    """Collapse runs of whitespace, including ideographic and no-break spaces, to one space.

    Args:
        text (str): Raw text.

    Returns:
        str: Text with single spaces and no leading or trailing whitespace.
    """
    return _SPACES.sub(" ", text).strip()


def compact(text: str) -> str:
    """Remove all whitespace and lowercase text, for matching headings and labels.

    Args:
        text (str): Raw text.

    Returns:
        str: Lowercased text without whitespace, so ``분 기 보 고 서`` equals ``분기보고서``.
    """
    return _SPACES.sub("", text).lower()


@dataclass(frozen=True, slots=True)
class Label:
    """Korean text with an optional English rendering from the filing's ``ENG`` attribute.

    Attributes:
        ko (str): Korean (original) text; may contain newlines between paragraphs.
        en (str | None): English text from ``ENG``, or None when absent.
    """

    ko: str
    en: str | None = None

    def text(self, mode: LabelMode) -> str:
        """Return the label in a label language.

        Args:
            mode (LabelMode): ``english`` uses ``ENG`` and falls back to Korean, ``korean``
                uses the original, and ``both`` renders ``English (Korean)``.

        Returns:
            str: The label text.
        """
        if not self.en or self.en == self.ko or mode == "korean":
            return self.ko
        if mode == "english" or not self.ko:
            return self.en
        return f"{self.en} ({self.ko})"


@dataclass(frozen=True, slots=True)
class Run:
    """A span of paragraph text with uniform weight.

    Attributes:
        text (str): Collapsed text of the span.
        bold (bool): Whether the filing marks the span as bold.
    """

    text: str
    bold: bool = False


@dataclass(frozen=True, slots=True)
class Paragraph:
    """A paragraph of narrative text.

    Attributes:
        runs (tuple[Run, ...]): Text spans in order.
    """

    runs: tuple[Run, ...]

    @property
    def plain(self) -> str:
        """Return the paragraph text without emphasis.

        Returns:
            str: Concatenated run text.
        """
        return "".join(run.text for run in self.runs)


@dataclass(frozen=True, slots=True)
class Subheading:
    """A heading that is not a table-of-contents entry, rendered inside its section.

    Attributes:
        label (Label): Heading text.
    """

    label: Label


@dataclass(frozen=True, slots=True)
class Image:
    """A reference to an image the archive does not include.

    Attributes:
        caption (str): Caption, or the image filename when there is no caption.
    """

    caption: str


@dataclass(frozen=True, slots=True)
class Cell:
    """A table cell before span expansion.

    Attributes:
        label (Label): Cell text (Korean, with newlines between paragraphs) and ``ENG``.
        colspan (int): Columns spanned, at least 1.
        rowspan (int): Rows spanned, at least 1.
        header (bool): Whether the cell is a header cell (``TH``, or inside ``THEAD``).
        value (bool): Whether the cell holds an entered value (``TE``/``TU``, or a KRX input).
    """

    label: Label
    colspan: int = 1
    rowspan: int = 1
    header: bool = False
    value: bool = False


@dataclass(frozen=True, slots=True)
class Table:
    """A table as written in the filing.

    Attributes:
        rows (tuple[tuple[Cell, ...], ...]): Rows of cells, spans unexpanded.
        bordered (bool): False for ``BORDER="0"`` tables, which DART uses for layout.
    """

    rows: tuple[tuple[Cell, ...], ...]
    bordered: bool = True


type Block = Paragraph | Subheading | Image | Table


@dataclass(frozen=True, slots=True)
class Section:
    """A titled section and its content in document order.

    Attributes:
        id (str): Stable section ID: the ``AASSOCNOTE`` code, ``s{ATOCID}``, or an ordinal path.
        level (int): Depth in the section tree, starting at 1.
        title (Label): Section heading.
        code (str | None): ``AASSOCNOTE`` code, when present.
        kind (SectionKind): Container kind: ``section``, ``cover``, ``correction``, or the
            single KRX ``body``.
        items (tuple[Block | Section, ...]): Blocks and subsections in document order.
        parent_id (str | None): ID of the enclosing section, or None at the top level.
    """

    id: str
    level: int
    title: Label
    code: str | None
    kind: SectionKind
    items: tuple[Block | Section, ...]
    parent_id: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentTree:
    """One parsed archive member.

    Attributes:
        format (DocumentFormat): ``dart_xml`` or ``krx_html``.
        items (tuple[Block | Section, ...]): Top-level blocks and sections in order.
        form_code (str | None): ``DOCUMENT-NAME ACODE`` form code (DART only).
        form_name_ko (str | None): Korean form name (``DOCUMENT-NAME`` or the KRX title's form).
        company_name (str | None): Korean company name from the document.
        corp_code (str | None): DART corporation code (``COMPANY-NAME AREGCIK``).
        title (str | None): KRX page title, or None for DART documents.
        cover_title_en (str | None): English cover title (``COVER-TITLE ENG``), when present.
    """

    format: DocumentFormat
    items: tuple[Block | Section, ...]
    form_code: str | None = None
    form_name_ko: str | None = None
    company_name: str | None = None
    corp_code: str | None = None
    title: str | None = None
    cover_title_en: str | None = None


def walk_sections(items: tuple[Block | Section, ...]) -> list[Section]:
    """List sections depth-first in document order.

    Args:
        items (tuple[Block | Section, ...]): Items to traverse.

    Returns:
        list[Section]: Every section among the items and their descendants.
    """
    found: list[Section] = []
    for item in items:
        if isinstance(item, Section):
            found.append(item)
            found.extend(walk_sections(item.items))
    return found


def walk_tables(items: tuple[Block | Section, ...]) -> list[Table]:
    """List tables depth-first in document order.

    Args:
        items (tuple[Block | Section, ...]): Items to search.

    Returns:
        list[Table]: Every table among the items and their subsections.
    """
    found: list[Table] = []
    for item in items:
        if isinstance(item, Table):
            found.append(item)
        elif isinstance(item, Section):
            found.extend(walk_tables(item.items))
    return found
