"""Lenient tag-soup builder shared by the DART XML and KRX HTML parsers.

``html.parser.HTMLParser`` tokenizes both formats: it tolerates unescaped ``&`` and unclosed
tags, never expands DTD entities, and never fetches external content. This builder keeps an
element stack, routes text to paragraphs, table cells, titles, and images, and assembles the
immutable model in :mod:`opendart_analysis.documents.tree`. Format-specific subclasses add sections
and metadata through ``_start_<hook>`` and ``_end_<hook>`` methods.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import TYPE_CHECKING, override

from opendart_analysis.documents.building import (
    CellBuilder,
    Frame,
    SectionBuilder,
    TableBuilder,
    freeze_items,
    is_bold,
    merge_runs,
    span,
)
from opendart_analysis.documents.errors import ArchiveTooLargeError
from opendart_analysis.documents.tree import Image, Label, Paragraph, Run, collapse

if TYPE_CHECKING:
    from collections.abc import Callable

    from opendart_analysis.documents.building import Attributes
    from opendart_analysis.documents.tree import Block, Section

_CELL_TAGS = frozenset({"td", "th", "te", "tu"})
_VALUE_CELL_TAGS = frozenset({"te", "tu"})
_CELL_SCOPE = frozenset({"td", "th", "te", "tu", "tr", "table"})
_ROW_TAGS = frozenset({"tr"})
_ROW_SCOPE = frozenset({"tr", "table", "tbody", "thead"})
_BLOCK_TAGS = frozenset(
    {"p", "div", "pgbrk", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "body", "center"}
)
_RAW_TEXT_EXEMPT = frozenset({"title", "textarea"})
_MAX_COLSPAN = 64
_MAX_ROWSPAN = 512
# The largest live member (7.9 MiB) has about 80,000 elements; the budget bounds memory for
# documents made of millions of tiny elements.
MAX_ELEMENTS = 500_000


class MarkupBuilder(HTMLParser):
    """Build a document tree from DART XML or KRX HTML markup.

    Subclasses define ``_start_<hook>(frame, attrs)`` and ``_end_<hook>(frame)`` for the tags
    they handle; :meth:`hook_name` maps tags to hooks.

    Attributes:
        frames (list[Frame]): Open elements, innermost last.
        root (SectionBuilder): Synthetic root that holds top-level items.
        open_sections (list[SectionBuilder]): Open sections, innermost last.
        runs (list[Run]): Text of the paragraph being collected.
        tables (list[TableBuilder]): Open tables, innermost last.
        capture (list[str] | None): Buffer for title or metadata text, when capturing.
        image_parts (dict[str, list[str]] | None): Text of the open image, by element.
    """

    VOID_TAGS: frozenset[str] = frozenset({"br"})
    SKIP_TAGS: frozenset[str] = frozenset({"style", "script", "noscript"})

    def __init__(self) -> None:
        """Start with an empty element stack and a synthetic root section."""
        super().__init__(convert_charrefs=True)
        self.frames: list[Frame] = []
        self.root = SectionBuilder("", 0, Label(""), None, "section", None)
        self.open_sections: list[SectionBuilder] = []
        self.runs: list[Run] = []
        self.tables: list[TableBuilder] = []
        self.capture: list[str] | None = None
        self.image_parts: dict[str, list[str]] | None = None
        self.elements = 0
        self._hooks: dict[str, Callable[..., None]] = {}

    @override
    def set_cdata_mode(self, elem: str, *, escapable: bool = False) -> None:
        """Parse ``title`` and ``textarea`` content as markup, not raw text.

        DART uses ``TITLE`` for section headings; raw-text mode would let one unclosed
        heading swallow the rest of the document.

        Args:
            elem (str): Element entering raw-text mode.
            escapable (bool): Whether character references are decoded inside it.
        """
        if elem.lower() not in _RAW_TEXT_EXEMPT:
            super().set_cdata_mode(elem, escapable=escapable)

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Push an element and run its start hook.

        Args:
            tag (str): Lowercased tag name.
            attrs (list[tuple[str, str | None]]): Attributes in source order.

        Raises:
            ArchiveTooLargeError: The member has more elements than the parser accepts.
        """
        self.elements += 1
        if self.elements > MAX_ELEMENTS:
            raise ArchiveTooLargeError(self.elements, MAX_ELEMENTS, measure="elements")
        attributes = dict(attrs)
        parent = self.frames[-1] if self.frames else None
        skip = (parent is not None and parent.skip) or self.skips(tag, attributes)
        if tag in self.VOID_TAGS:
            if not skip:
                self.void(tag, attributes)
            return
        self.auto_close(tag)
        bold = self.style_bold(tag, attributes)
        inherited = parent.bold if parent is not None else False
        frame = Frame(tag, inherited if bold is None else bold, skip, len(self.open_sections))
        self.frames.append(frame)
        if not skip:
            self.dispatch("_start_", frame, attributes)

    @override
    def handle_endtag(self, tag: str) -> None:
        """Close an open element and any unclosed elements inside it.

        End tags with no matching open element are ignored.

        Args:
            tag (str): Lowercased tag name.
        """
        for index in range(len(self.frames) - 1, -1, -1):
            if self.frames[index].tag == tag:
                self.unwind(index)
                return

    @override
    def handle_data(self, data: str) -> None:
        """Route text to the open title, image, table cell, or paragraph.

        Args:
            data (str): Text with character references decoded.
        """
        top = self.frames[-1] if self.frames else Frame("")
        if self.capture is not None:
            self.capture.append(data)
        elif top.skip:
            return
        elif self.image_parts is not None:
            self.image_parts.setdefault(top.tag, []).append(data)
        elif self.tables:
            self.cell_text(data)
        else:
            self.runs.append(Run(data, top.bold))

    def style_bold(self, tag: str, attrs: Attributes) -> bool | None:
        """Decide whether an element makes its text bold.

        Args:
            tag (str): Lowercased tag name.
            attrs (Attributes): Element attributes.

        Returns:
            bool | None: The weight the element sets, or None to inherit it.
        """
        if tag in {"b", "strong"}:
            return True
        return is_bold(attrs.get("usermark"))

    def skips(self, tag: str, attrs: Attributes) -> bool:
        """Decide whether an element's content is ignored.

        Args:
            tag (str): Lowercased tag name.
            attrs (Attributes): Element attributes.

        Returns:
            bool: True to ignore the element and everything inside it.
        """
        del attrs
        return tag in self.SKIP_TAGS

    def hook_name(self, tag: str) -> str:
        """Map a tag name to its hook suffix.

        Args:
            tag (str): Lowercased tag name.

        Returns:
            str: Hook suffix, such as ``cell`` for every table cell tag.
        """
        if tag in _CELL_TAGS:
            return "cell"
        if tag in _BLOCK_TAGS:
            return "block"
        return tag.replace("-", "_").replace(":", "_")

    def dispatch(self, prefix: str, frame: Frame, attrs: Attributes | None) -> None:
        """Call the element's start or end hook when the builder defines one.

        Args:
            prefix (str): ``_start_`` or ``_end_``.
            frame (Frame): The element's frame.
            attrs (Attributes | None): Attributes for start hooks; None for end hooks.
        """
        name = prefix + self.hook_name(frame.tag)
        hook = self._hooks.get(name)
        if hook is None:
            hook = self._hooks.setdefault(name, getattr(self, name, _ignore))
        if attrs is None:
            hook(frame)
        else:
            hook(frame, attrs)

    def unwind(self, index: int) -> None:
        """Pop frames down to ``index``, running end hooks innermost first.

        Args:
            index (int): Stack position of the element being closed.
        """
        while len(self.frames) > index:
            frame = self.frames.pop()
            if not frame.skip:
                self.dispatch("_end_", frame, None)

    def auto_close(self, tag: str) -> None:
        """Close cells and rows that HTML allows to be left open.

        Args:
            tag (str): Tag about to open.
        """
        if tag in _CELL_TAGS:
            self.close_open(_CELL_TAGS, _CELL_SCOPE)
        elif tag == "tr":
            self.close_open(_ROW_TAGS, _ROW_SCOPE)

    def close_open(self, targets: frozenset[str], scope: frozenset[str]) -> None:
        """Close the innermost open target element unless a scope boundary comes first.

        Args:
            targets (frozenset[str]): Tags to close.
            scope (frozenset[str]): Tags that bound the search, including the targets.
        """
        for index in range(len(self.frames) - 1, -1, -1):
            tag = self.frames[index].tag
            if tag in scope:
                if tag in targets:
                    self.unwind(index)
                return

    def void(self, tag: str, attrs: Attributes) -> None:
        """Handle an element without content, such as ``br``.

        Args:
            tag (str): Lowercased tag name.
            attrs (Attributes): Element attributes.
        """
        if tag == "br":
            self.paragraph_break()
        else:
            self.dispatch("_start_", Frame(tag), attrs)

    def open_cell(self) -> CellBuilder | None:
        """Return the cell being filled, if any.

        Returns:
            CellBuilder | None: The innermost table's open cell.
        """
        return self.tables[-1].cell if self.tables else None

    def cell_text(self, data: str) -> None:
        """Append text to the open cell; text between cells is layout whitespace.

        Args:
            data (str): Text to append.
        """
        cell = self.open_cell()
        if cell is not None:
            cell.parts.append(data)

    def paragraph_break(self) -> None:
        """Break a paragraph: a newline inside a cell, the end of a paragraph elsewhere."""
        cell = self.open_cell()
        if cell is not None:
            cell.parts.append("\n")
        elif self.capture is None:
            self.flush()

    def current(self) -> SectionBuilder:
        """Return the section that receives new blocks.

        Returns:
            SectionBuilder: The innermost open section, or the synthetic root.
        """
        return self.open_sections[-1] if self.open_sections else self.root

    def emit(self, block: Block) -> None:
        """Append a block to the current section.

        Args:
            block (Block): Block to append.
        """
        self.current().items.append(block)

    def flush(self) -> None:
        """End the current paragraph, dropping it when it holds only whitespace."""
        runs = self.runs
        self.runs = []
        merged = merge_runs(runs)
        if merged:
            self.emit(Paragraph(tuple(merged)))

    def place_image(self, caption: str) -> None:
        """Place an image reference into the open cell or as a block.

        Args:
            caption (str): Caption or filename.
        """
        text = collapse(caption) or "image"
        cell = self.open_cell()
        if cell is not None:
            cell.parts.append(f" [image not included: {text}] ")
            return
        self.flush()
        self.emit(Image(text))

    def finish_items(self) -> list[Block | Section]:
        """Close every open element and freeze the top-level items.

        Returns:
            list[Block | Section]: Top-level items in document order.
        """
        self.close()
        self.unwind(0)
        while self.tables:
            self._end_table(Frame("table"))
        self.flush()
        return freeze_items(self.root.items)

    # Hooks shared by both formats ---------------------------------------------------------

    def _start_block(self, frame: Frame, attrs: Attributes) -> None:
        """End the open paragraph at a block-level start tag.

        Args:
            frame (Frame): Frame for the opening element, currently unused.
            attrs (Attributes): Element attributes, currently unused.
        """
        del frame, attrs
        self.paragraph_break()

    def _end_block(self, frame: Frame) -> None:
        """End the open paragraph at a block-level end tag.

        Args:
            frame (Frame): Frame for the closing element.
        """
        del frame
        self.paragraph_break()

    def _start_table(self, frame: Frame, attrs: Attributes) -> None:
        """Open a table, or flatten a table nested inside an open cell.

        Args:
            frame (Frame): Frame for the table element, currently unused.
            attrs (Attributes): Table attributes used to determine its border.
        """
        del frame
        if self.open_cell() is not None:
            self.tables[-1].nested += 1
            return
        self.flush()
        self.tables.append(TableBuilder(bordered=(attrs.get("border") or "1").strip() != "0"))

    def _end_table(self, frame: Frame) -> None:
        """Close a table and emit it, or close a flattened nested table.

        Args:
            frame (Frame): Frame for the closing table element, currently unused.
        """
        del frame
        if not self.tables:
            return
        table = self.tables[-1]
        if table.nested:
            table.nested -= 1
            self.cell_text("\n")
            return
        self.tables.pop()
        finished = table.finish()
        if finished is not None:
            self.emit(finished)

    def _start_thead(self, frame: Frame, attrs: Attributes) -> None:
        """Mark following rows as header rows.

        Args:
            frame (Frame): Frame for the table-head element, currently unused.
            attrs (Attributes): Table-head attributes, currently unused.
        """
        del frame, attrs
        if self.tables and not self.tables[-1].nested:
            self.tables[-1].in_head = True

    def _end_thead(self, frame: Frame) -> None:
        """Stop marking rows as header rows.

        Args:
            frame (Frame): Frame for the closing table-head element.
        """
        del frame
        if self.tables and not self.tables[-1].nested:
            self.tables[-1].in_head = False

    def _start_tr(self, frame: Frame, attrs: Attributes) -> None:
        """Start a row, or separate the rows of a flattened nested table.

        Args:
            frame (Frame): Frame for the row element, currently unused.
            attrs (Attributes): Row attributes, currently unused.
        """
        del frame, attrs
        if not self.tables:
            return
        table = self.tables[-1]
        if table.nested:
            self.cell_text("\n")
            return
        table.close_row()
        table.row = []

    def _end_tr(self, frame: Frame) -> None:
        """Finish a row.

        Args:
            frame (Frame): Frame for the closing row element.
        """
        del frame
        if self.tables and not self.tables[-1].nested:
            self.tables[-1].close_row()

    def _start_cell(self, frame: Frame, attrs: Attributes) -> None:
        """Open a ``TD``, ``TH``, ``TE``, or ``TU`` cell.

        Args:
            frame (Frame): Cell frame, including its tag name.
            attrs (Attributes): Cell attributes such as spans and English label.
        """
        if not self.tables:
            return
        table = self.tables[-1]
        if table.nested:
            self.cell_text(" ")
            return
        table.close_cell()
        table.cell = CellBuilder(
            eng=attrs.get("eng"),
            colspan=span(attrs.get("colspan"), _MAX_COLSPAN),
            rowspan=span(attrs.get("rowspan"), _MAX_ROWSPAN),
            header=frame.tag == "th" or table.in_head,
            value=frame.tag in _VALUE_CELL_TAGS,
        )

    def _end_cell(self, frame: Frame) -> None:
        """Close the open cell.

        Args:
            frame (Frame): Frame for the closing cell element.
        """
        del frame
        if self.tables and not self.tables[-1].nested:
            self.tables[-1].close_cell()


def _ignore(*args: object) -> None:
    """Accept and ignore a hook call for a tag without a handler.

    Args:
        *args (object): Hook arguments.
    """
    del args
