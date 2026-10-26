"""Paging over rendered Markdown: scopes, page cuts, repeated table headers, and typed rows.

A scope is the whole document or one or more section subtrees read as one text. Pages end at
a blank line or line break in their second half, so table rows are never split; a page that
starts inside a table repeats the table's header, which is not counted in offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_analysis.documents.models import TableData
from opendart_analysis.documents.tables import view

if TYPE_CHECKING:
    from opendart_analysis.documents.models import LabelMode
    from opendart_analysis.documents.render import Rendering, TableSpan

_GAP = "\n\n"
_SNAP = 300


@dataclass(frozen=True, slots=True)
class Scope:
    """Ranges of a rendering read as one text, joined by a blank line where not adjacent.

    Attributes:
        ranges (tuple[tuple[int, int], ...]): Start and end offsets in the rendering, ascending.
        starts (tuple[int, ...]): Offset of each range within the scope text.
        length (int): Length of the scope text.
    """

    ranges: tuple[tuple[int, int], ...]
    starts: tuple[int, ...]
    length: int

    @classmethod
    def of(cls, spans: list[tuple[int, int]]) -> Scope:
        """Build a scope from section spans, merging adjacent or overlapping ones.

        Args:
            spans (list[tuple[int, int]]): Start and end offsets in the rendering.

        Returns:
            Scope: The scope.
        """
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1] + len(_GAP):
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        starts: list[int] = []
        position = 0
        for index, (start, end) in enumerate(merged):
            position += len(_GAP) if index else 0
            starts.append(position)
            position += end - start
        return cls(tuple(merged), tuple(starts), position)

    def text(self, full: str) -> str:
        """Return the scope's text.

        Args:
            full (str): The whole rendering.

        Returns:
            str: Concatenated ranges.
        """
        return _GAP.join(full[start:end] for start, end in self.ranges)

    def relative(self, absolute: int) -> int | None:
        """Map a rendering offset into the scope.

        Args:
            absolute (int): Offset in the rendering.

        Returns:
            int | None: Offset in the scope text, or None when outside the scope.
        """
        for (start, end), base in zip(self.ranges, self.starts, strict=True):
            if start <= absolute <= end:
                return base + absolute - start
        return None

    def absolute(self, relative: int) -> int:
        """Map a scope offset back into the rendering.

        Args:
            relative (int): Offset in the scope text.

        Returns:
            int: Offset in the rendering; offsets in a joining gap map to the next range.
        """
        for (start, end), base in zip(self.ranges, self.starts, strict=True):
            if relative <= base + end - start:
                return start + max(relative - base, 0)
        return self.ranges[-1][1] if self.ranges else 0


@dataclass(frozen=True, slots=True)
class Page:
    """One page of a scope.

    Attributes:
        content (str): Markdown, with a repeated table header when the page starts in a table.
        start (int): Scope offset where the page starts, at a line start when one is close.
        end (int): Scope offset just past the page.
        tables (list[TableData]): Typed rows of tables on the page.
        notes (list[str]): Notes about split tables.
    """

    content: str
    start: int
    end: int
    tables: list[TableData]
    notes: list[str]


@dataclass(frozen=True, slots=True)
class _Placed:
    """A table's position within a scope."""

    span: TableSpan
    start: int
    body: int
    end: int
    rows: tuple[int, ...]


def read_page(
    rendering: Rendering, scope: Scope, window: tuple[int, int], *, mode: LabelMode
) -> Page:
    """Cut one page from a scope.

    Args:
        rendering (Rendering): The rendering the scope refers to.
        scope (Scope): Ranges to read.
        window (tuple[int, int]): Start offset within the scope and the page size in
            characters; the start must be below ``scope.length``.
        mode (LabelMode): Label language of the rendering.

    Returns:
        Page: The page.
    """
    text = scope.text(rendering.text)
    offset, size = _line_start(text, window[0], window[1]), window[1]
    placed = _place(rendering, scope)
    end = _page_end(text, offset, size, placed=placed)
    content = text[offset:end].strip("\n")
    notes: list[str] = []
    for table in placed:
        if table.start < offset < table.end and table.span.header and offset >= table.body:
            content = f"{table.span.header}\n{content}"
            notes.append(
                "This page continues a table from the previous page; its header is repeated."
            )
        if table.body < end < table.end:
            notes.append("A table continues on the next page; its header is repeated there.")
    tables = [
        data for table in placed if (data := _rows(table, offset, end, mode=mode)) is not None
    ]
    return Page(content, offset, end, tables, notes)


def _line_start(text: str, offset: int, size: int) -> int:
    """Move an offset back to the start of its line when that is close.

    The bound stays below half a page, so a page that had to cut a very long line never
    snaps back over its own content.

    Args:
        text (str): Scope text.
        offset (int): Requested offset.
        size (int): Page size.

    Returns:
        int: The line start, or the offset when the line starts too far back.
    """
    line = text.rfind("\n", 0, offset) + 1
    return line if offset - line <= min(_SNAP, size // 4) else offset


def _place(rendering: Rendering, scope: Scope) -> list[_Placed]:
    """Map the rendering's tables into scope offsets.

    Args:
        rendering (Rendering): The rendering.
        scope (Scope): The scope.

    Returns:
        list[_Placed]: Tables that lie inside the scope, in order.
    """
    placed: list[_Placed] = []
    for span in rendering.tables:
        start, end = scope.relative(span.start), scope.relative(span.end)
        if start is None or end is None:
            continue
        rows = tuple(start + row - span.start for row in span.rows)
        placed.append(_Placed(span, start, rows[0] if rows else end, end, rows))
    return placed


def _page_end(text: str, offset: int, size: int, *, placed: list[_Placed]) -> int:
    """Choose where a page ends: at a block or line boundary, never inside a table header.

    Args:
        text (str): Scope text.
        offset (int): Page start.
        size (int): Page size in characters.
        placed (list[_Placed]): Tables in the scope.

    Returns:
        int: Offset just past the page.
    """
    limit = offset + size
    if limit >= len(text):
        return len(text)
    floor = offset + size // 2
    cut = text.rfind(_GAP, floor, limit)
    end = cut + len(_GAP) if cut >= 0 else text.rfind("\n", floor, limit) + 1
    end = end if end > offset else limit
    for table in placed:
        if table.start < end < table.body and table.start > offset:
            return table.start
    return end


def _rows(table: _Placed, offset: int, end: int, *, mode: LabelMode) -> TableData | None:
    """Build typed rows for the part of a table that lies on a page.

    Args:
        table (_Placed): Table position.
        offset (int): Page start.
        end (int): Page end.
        mode (LabelMode): Label language.

    Returns:
        TableData | None: The rows on the page, or None when the table is not on the page.
    """
    indexes = [index for index, row in enumerate(table.rows) if offset <= row < end]
    if not indexes and not offset <= table.start < end:
        return None
    shown = view(table.span.table, mode)
    first = indexes[0] if indexes else 0
    last = indexes[-1] + 1 if indexes else 0
    return TableData(
        caption=table.span.caption,
        unit=table.span.unit,
        header=shown.header,
        rows=shown.rows[first:last],
        layout=table.span.layout,
        section_id=table.span.section_id,
        first_row=first,
        total_rows=len(shown.rows),
    )
