"""Mutable builders used while parsing: element frames, table cells, tables, and sections.

The markup builder fills these as tags stream past and freezes them into the immutable model
of :mod:`opendart_mcp.documents.tree` when the document ends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opendart_mcp.documents.tree import Cell, Label, Run, Section, Table, collapse

if TYPE_CHECKING:
    from opendart_mcp.documents.tree import Block, SectionKind

type Attributes = dict[str, str | None]

_BOLD_TOKEN = re.compile(r"[IBU]+")
_INLINE_SPACES = re.compile(r"[^\S\n]+")
_SPACES = re.compile(r"\s+")


@dataclass(slots=True)
class Frame:
    """An open element on the builder's stack.

    Attributes:
        tag (str): Lowercased tag name.
        bold (bool): Whether text inside is bold.
        skip (bool): Whether the element's content is ignored.
        sections (int): Number of open sections when the element started.
        titled (bool): For section containers, whether the heading has been seen.
        attrs (Attributes | None): Attributes kept for end-tag handling, when needed.
    """

    tag: str
    bold: bool = False
    skip: bool = False
    sections: int = 0
    titled: bool = False
    attrs: Attributes | None = None


@dataclass(slots=True)
class CellBuilder:
    """A table cell being filled.

    Attributes:
        eng (str | None): ``ENG`` attribute.
        colspan (int): Columns spanned.
        rowspan (int): Rows spanned.
        header (bool): Whether this is a header cell.
        value (bool): Whether this cell holds an entered value.
        parts (list[str]): Text fragments; a newline separates paragraphs.
    """

    eng: str | None
    colspan: int
    rowspan: int
    header: bool
    value: bool
    parts: list[str] = field(default_factory=list)

    def finish(self) -> Cell:
        """Freeze the cell, keeping one line per paragraph.

        Returns:
            Cell: The finished cell.
        """
        lines = (_INLINE_SPACES.sub(" ", line).strip() for line in "".join(self.parts).split("\n"))
        text = "\n".join(line for line in lines if line)
        english = collapse(self.eng) if self.eng else None
        return Cell(Label(text, english), self.colspan, self.rowspan, self.header, self.value)


@dataclass(slots=True)
class TableBuilder:
    """A table being filled; tables nested inside a cell are flattened into that cell.

    Attributes:
        bordered (bool): False for ``BORDER="0"`` layout tables.
        rows (list[tuple[Cell, ...]]): Finished rows.
        row (list[Cell] | None): Row being filled.
        cell (CellBuilder | None): Cell being filled.
        in_head (bool): Whether rows are inside ``THEAD``.
        nested (int): Depth of tables nested inside the open cell.
    """

    bordered: bool
    rows: list[tuple[Cell, ...]] = field(default_factory=list)
    row: list[Cell] | None = None
    cell: CellBuilder | None = None
    in_head: bool = False
    nested: int = 0

    def close_cell(self) -> None:
        """Finish the open cell, if any, into the current row."""
        if self.cell is not None:
            if self.row is None:
                self.row = []
            self.row.append(self.cell.finish())
            self.cell = None

    def close_row(self) -> None:
        """Finish the open cell and row, if any."""
        self.close_cell()
        if self.row:
            self.rows.append(tuple(self.row))
        self.row = None

    def finish(self) -> Table | None:
        """Freeze the table.

        Returns:
            Table | None: The table, or None when no cell has text.
        """
        self.close_row()
        if not any(cell.label.ko or cell.label.en for row in self.rows for cell in row):
            return None
        return Table(tuple(self.rows), self.bordered)


@dataclass(slots=True)
class SectionBuilder:
    """A section being filled.

    Attributes:
        id (str): Section ID.
        level (int): Depth in the section tree; 0 for the synthetic root.
        title (Label): Heading.
        code (str | None): ``AASSOCNOTE`` code.
        kind (SectionKind): Container kind.
        parent_id (str | None): Enclosing section ID.
        path (tuple[int, ...]): Ordinal path from the root.
        items (list[Block | SectionBuilder]): Content in document order.
        children (int): Number of child sections so far.
    """

    id: str
    level: int
    title: Label
    code: str | None
    kind: SectionKind
    parent_id: str | None
    path: tuple[int, ...] = ()
    items: list[Block | SectionBuilder] = field(default_factory=list)
    children: int = 0

    def freeze(self) -> Section:
        """Freeze this section and its descendants.

        Returns:
            Section: The immutable section.
        """
        items = tuple(freeze_items(self.items))
        return Section(self.id, self.level, self.title, self.code, self.kind, items, self.parent_id)


def freeze_items(items: list[Block | SectionBuilder]) -> list[Block | Section]:
    """Freeze section builders among items, keeping blocks as they are.

    Args:
        items (list[Block | SectionBuilder]): Mixed blocks and builders.

    Returns:
        list[Block | Section]: Immutable items in the same order.
    """
    return [item.freeze() if isinstance(item, SectionBuilder) else item for item in items]


def span(value: str | None, limit: int) -> int:
    """Parse a ``COLSPAN`` or ``ROWSPAN`` attribute, bounded to keep grids small.

    Args:
        value (str | None): Attribute value.
        limit (int): Largest accepted span.

    Returns:
        int: Span between 1 and the limit; invalid values count as 1.
    """
    digits = (value or "").strip()
    return min(max(int(digits), 1), limit) if digits.isdigit() else 1


def is_bold(usermark: str | None) -> bool | None:
    """Interpret a DART ``USERMARK`` style string.

    ``USERMARK`` mixes tokens such as ``B`` (bold), ``BU``, ``F-GL11`` (font), ``A-C``
    (alignment), and ``BC0XD9D9D9`` (background color), so bold is a whole-token flag.

    Args:
        usermark (str | None): Attribute value.

    Returns:
        bool | None: True for bold, False for an explicit ``!B``, None when unspecified.
    """
    tokens = (usermark or "").split()
    if "!B" in tokens:
        return False
    if any(_BOLD_TOKEN.fullmatch(token) and "B" in token for token in tokens):
        return True
    return None


def merge_runs(runs: list[Run]) -> list[Run]:
    """Collapse whitespace across runs and merge neighbors of equal weight.

    Args:
        runs (list[Run]): Raw runs in order.

    Returns:
        list[Run]: Merged runs, or an empty list when the text is blank.
    """
    merged: list[Run] = []
    for run in runs:
        text = _SPACES.sub(" ", run.text)
        blank = not text.strip()
        if merged and (blank or merged[-1].bold == run.bold):
            merged[-1] = Run(merged[-1].text + text, merged[-1].bold)
        elif text:
            merged.append(Run(text, run.bold and not blank))
    return _trim_runs(merged)


def _trim_runs(runs: list[Run]) -> list[Run]:
    """Remove doubled spaces at run boundaries and the paragraph's outer whitespace.

    Args:
        runs (list[Run]): Merged runs.

    Returns:
        list[Run]: Trimmed, non-empty runs.
    """
    trimmed: list[Run] = []
    for run in runs:
        text = run.text
        if not trimmed or trimmed[-1].text.endswith(" "):
            text = text.lstrip()
        if text:
            trimmed.append(Run(text, run.bold))
    if trimmed:
        trimmed[-1] = Run(trimmed[-1].text.rstrip(), trimmed[-1].bold)
    return [run for run in trimmed if run.text]
