"""Render a document tree as Markdown with section and table positions.

The whole document renders to one string in document order. Each section's subtree is a
contiguous slice, so section reads, paging, and search work on character offsets. Tables
record their header block and row offsets, so a page that starts inside a table can repeat the
header and typed rows can be cut to the page.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opendart_analysis.documents.tables import form_lines, markdown_grid, view
from opendart_analysis.documents.tree import Image, Paragraph, Section, Subheading, Table
from opendart_analysis.documents.units import find_unit_statement

if TYPE_CHECKING:
    from opendart_analysis.documents.models import LabelMode, TableLayout
    from opendart_analysis.documents.tables import TableView
    from opendart_analysis.documents.tree import Block, DocumentTree
    from opendart_analysis.documents.units import UnitStatement

_MAX_HEADING_LEVEL = 6
_MAX_CAPTION = 150
_SEPARATOR = "\n\n"


@dataclass(frozen=True, slots=True)
class TableSpan:
    """Where a table sits in a rendering.

    Attributes:
        table (Table): The table as written, for typed output.
        section_id (str | None): Section containing the table.
        start (int): Offset of the table block (its unit line, if any).
        end (int): Offset just past the table block.
        header (str): Unit line and Markdown header lines to repeat on a continuation page;
            empty for ``label: value`` tables.
        rows (tuple[int, ...]): Offset of each body row line.
        layout (TableLayout): ``grid`` or ``form``.
        unit (str | None): Unit statement in English.
        caption (str | None): Short text that introduces the table.
    """

    table: Table
    section_id: str | None
    start: int
    end: int
    header: str
    rows: tuple[int, ...]
    layout: TableLayout
    unit: str | None
    caption: str | None


@dataclass(frozen=True, slots=True)
class Rendering:
    """A document rendered in one label language.

    Attributes:
        text (str): Markdown for the whole document.
        spans (dict[str, tuple[int, int]]): Start and end offsets of each section's subtree.
        tables (tuple[TableSpan, ...]): Tables in document order.
        marks (tuple[int, ...]): Offsets where the innermost section changes, ascending.
        owners (tuple[str | None, ...]): Innermost section from each mark onward.
    """

    text: str
    spans: dict[str, tuple[int, int]]
    tables: tuple[TableSpan, ...]
    marks: tuple[int, ...]
    owners: tuple[str | None, ...]

    def owner(self, position: int) -> str | None:
        """Return the innermost section containing an offset.

        Args:
            position (int): Offset in :attr:`text`.

        Returns:
            str | None: Section ID, or None for content outside every section.
        """
        index = bisect.bisect_right(self.marks, position) - 1
        return self.owners[index] if index >= 0 else None


@dataclass(slots=True)
class _Context:
    """Unit and caption carried from a table's preceding block."""

    unit: UnitStatement | None = None
    caption: str | None = None


@dataclass(slots=True)
class _Renderer:
    """Accumulate rendered blocks and positions."""

    mode: LabelMode
    parts: list[str] = field(default_factory=list)
    pos: int = 0
    spans: dict[str, tuple[int, int]] = field(default_factory=dict)
    tables: list[TableSpan] = field(default_factory=list)
    marks: list[int] = field(default_factory=lambda: [0])
    owners: list[str | None] = field(default_factory=lambda: _owners(None))

    def block(self, text: str) -> int:
        """Append a block after a blank line and return its offset.

        Args:
            text (str): Block text without surrounding blank lines.

        Returns:
            int: Offset of the block's first character.
        """
        if self.parts:
            self.parts.append(_SEPARATOR)
            self.pos += len(_SEPARATOR)
        start = self.pos
        self.parts.append(text)
        self.pos += len(text)
        return start

    def mark(self, section_id: str | None) -> None:
        """Record that content from the current offset belongs to a section.

        Args:
            section_id (str | None): Section ID, or None outside sections.
        """
        if self.marks[-1] == self.pos:
            self.owners[-1] = section_id
        else:
            self.marks.append(self.pos)
            self.owners.append(section_id)

    def finish(self) -> Rendering:
        """Freeze the rendering.

        Returns:
            Rendering: Text and positions.
        """
        return Rendering(
            "".join(self.parts),
            self.spans,
            tuple(self.tables),
            tuple(self.marks),
            tuple(self.owners),
        )


def _owners(first: str | None) -> list[str | None]:
    """Start the list of section owners.

    Args:
        first (str | None): Owner of the document start.

    Returns:
        list[str | None]: A one-element list.
    """
    return [first]


def render(tree: DocumentTree, mode: LabelMode) -> Rendering:
    """Render a document as Markdown in a label language.

    Args:
        tree (DocumentTree): Parsed document.
        mode (LabelMode): ``english``, ``korean``, or ``both``.

    Returns:
        Rendering: Text with section and table positions.
    """
    renderer = _Renderer(mode)
    _items(renderer, tree.items, None)
    return renderer.finish()


def heading(section: Section, mode: LabelMode) -> str:
    """Render a section heading with its ID in brackets.

    Args:
        section (Section): Section to head.
        mode (LabelMode): Label language.

    Returns:
        str: Markdown heading such as ``## 1. Company overview [D-0-1-1-0]``.
    """
    hashes = "#" * min(max(section.level, 1), _MAX_HEADING_LEVEL)
    return f"{hashes} {section.title.text(mode)} [{section.id}]"


def paragraph_markdown(paragraph: Paragraph) -> str:
    """Render a paragraph with bold spans as Markdown emphasis.

    Args:
        paragraph (Paragraph): Paragraph to render.

    Returns:
        str: Markdown text; a leading ``#`` is escaped so it is not read as a heading.
    """
    pieces: list[str] = []
    for run in paragraph.runs:
        core = run.text.strip()
        if run.bold and core:
            lead = run.text[: len(run.text) - len(run.text.lstrip())]
            trail = run.text[len(run.text.rstrip()) :]
            pieces.append(f"{lead}**{core}**{trail}")
        else:
            pieces.append(run.text)
    text = "".join(pieces)
    return "\\" + text if text.startswith("#") else text


def _items(renderer: _Renderer, items: tuple[Block | Section, ...], section_id: str | None) -> None:
    """Render a sequence of blocks and subsections.

    Args:
        renderer (_Renderer): Output accumulator.
        items (tuple[Block | Section, ...]): Items in document order.
        section_id (str | None): Section that owns the blocks.
    """
    context = _Context()
    for index, item in enumerate(items):
        following = items[index + 1] if index + 1 < len(items) else None
        if isinstance(item, Section):
            context.unit = context.caption = None
            _section(renderer, item, section_id)
        elif isinstance(item, Table):
            _table(
                renderer,
                item,
                section_id=section_id,
                context=context,
                before_table=isinstance(following, Table),
            )
        else:
            _text_block(renderer, item, context)


def _section(renderer: _Renderer, section: Section, parent_id: str | None) -> None:
    """Render a section heading and its content, recording its span.

    Args:
        renderer (_Renderer): Output accumulator.
        section (Section): Section to render.
        parent_id (str | None): Enclosing section ID.
    """
    if renderer.parts:
        renderer.parts.append(_SEPARATOR)
        renderer.pos += len(_SEPARATOR)
    renderer.mark(section.id)
    start = renderer.pos
    text = heading(section, renderer.mode)
    renderer.parts.append(text)
    renderer.pos += len(text)
    _items(renderer, section.items, section.id)
    renderer.spans[section.id] = (start, renderer.pos)
    renderer.mark(parent_id)


def _text_block(renderer: _Renderer, block: Block, context: _Context) -> None:
    """Render a paragraph, subheading, or image, and update the table context.

    A paragraph that states a unit (``... [단위 : 건]``) passes it to the next table.

    Args:
        renderer (_Renderer): Output accumulator.
        block (Block): Block to render.
        context (_Context): Unit and caption carried to the next table.
    """
    context.unit = context.caption = None
    if isinstance(block, Paragraph):
        plain = block.plain
        context.unit = find_unit_statement(plain)
        context.caption = plain if len(plain) <= _MAX_CAPTION else None
        renderer.block(paragraph_markdown(block))
    elif isinstance(block, Subheading):
        text = block.label.text(renderer.mode)
        context.caption = text
        renderer.block(f"**{text}**")
    elif isinstance(block, Image):
        renderer.block(f"[image not included: {block.caption}]")


def _table(
    renderer: _Renderer,
    table: Table,
    *,
    section_id: str | None,
    context: _Context,
    before_table: bool,
) -> None:
    """Render a table, or pass a caption table's unit and text on to the next table.

    Args:
        renderer (_Renderer): Output accumulator.
        table (Table): Table to render.
        section_id (str | None): Owning section ID.
        context (_Context): Unit and caption carried from the preceding block.
        before_table (bool): Whether the next item is a table.
    """
    shown = view(table, renderer.mode)
    if before_table and shown.layout == "form" and all(len(line) <= 1 for line in shown.lines):
        _caption_table(renderer, shown, context)
        return
    unit = shown.unit or context.unit
    caption, context.unit, context.caption = context.caption, None, None
    _emit_table(renderer, table, shown, where=(section_id, unit, caption))


def _caption_table(renderer: _Renderer, shown: TableView, context: _Context) -> None:
    """Render a one-column layout table and carry its unit and text to the next table.

    DART puts statement titles, periods, and ``(단위 : 원)`` in such a table just before the
    data table; the unit cell itself is not repeated in the lines.

    Args:
        renderer (_Renderer): Output accumulator.
        shown (TableView): The caption table's view.
        context (_Context): Context to update.
    """
    texts = [line[0][0] for line in shown.lines if line]
    if texts:
        renderer.block("\n".join(form_lines(shown.lines)))
    context.unit = shown.unit or context.unit
    caption = " / ".join(text.replace("\n", " ") for text in texts)
    context.caption = caption if 0 < len(caption) <= _MAX_CAPTION else context.caption


def _emit_table(
    renderer: _Renderer,
    table: Table,
    shown: TableView,
    *,
    where: tuple[str | None, UnitStatement | None, str | None],
) -> None:
    """Append a table block and record its span.

    Args:
        renderer (_Renderer): Output accumulator.
        table (Table): Table as written.
        shown (TableView): Its cleaned view.
        where (tuple[str | None, UnitStatement | None, str | None]): Section ID, unit, and
            caption.
    """
    section_id, unit, caption = where
    unit_line = f"Unit: {unit.english}" if unit is not None else ""
    if shown.layout == "grid":
        head, lines = markdown_grid(shown.header, shown.rows)
        header = f"{unit_line}\n{head}" if unit_line else head
    else:
        lines, header = form_lines(shown.lines), unit_line
    if not lines and not unit_line:
        return
    trailer = ["(Table truncated: it is too large to render in full.)"] if shown.truncated else []
    text = "\n".join([*([header] if header else []), *lines, *trailer])
    start = renderer.block(text)
    offset = start + len(header) + (1 if header else 0)
    rows: list[int] = []
    for line in lines:
        rows.append(offset)
        offset += len(line) + 1
    renderer.tables.append(
        TableSpan(
            table=table,
            section_id=section_id,
            start=start,
            end=renderer.pos,
            header=header,
            rows=tuple(rows),
            layout=shown.layout,
            unit=unit.english if unit is not None else None,
            caption=caption,
        )
    )
