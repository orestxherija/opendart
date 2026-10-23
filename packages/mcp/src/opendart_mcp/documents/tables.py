"""Table layout: span expansion, cleanup, unit extraction, and Markdown rendering.

Rows and column spans are expanded into a rectangular grid. Row-spanned cells repeat so each
row stands alone; column-spanned cells keep their text in the first column only (headers
repeat it so stacked header rows combine per column). Columns that only duplicate a neighbor's
span and fully empty rows and columns are dropped. Numbers stay verbatim.

Tables without header cells render as ``label: value`` lines when the filing marks entered
values (``TE``/``TU`` cells, KRX inputs) and every row pairs labels with at most two values, or,
without such marks, when every row has at most three distinct cells. Everything else renders
as a Markdown table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_mcp.documents.tree import Label
from opendart_mcp.documents.units import find_unit_statement, is_unit_only

if TYPE_CHECKING:
    from opendart_mcp.documents.models import LabelMode, TableLayout
    from opendart_mcp.documents.tree import Cell, Table
    from opendart_mcp.documents.units import UnitStatement

_MAX_WIDTH = 200
# Live tables cover at most about 11,000 grid positions; larger grids are cut by rows.
MAX_GRID_SLOTS = 200_000
_CONNECTOR = re.compile(r"[^\w]{1,3}")
_LABEL_END = re.compile("\\s*[:\uff1a]+\\s*$")
_FORM_MAX_CELLS = 3
_FORM_MAX_VALUE_RUN = 2
_MIN_HEADER_CELLS = 2
_MIN_ROWS_WITH_HEADER = 2


@dataclass(frozen=True, slots=True)
class Slot:
    """One grid position covered by a cell.

    Attributes:
        cell (Cell): The covering cell.
        lead (bool): Whether this is the cell's first column (not a column-span copy).
    """

    cell: Cell
    lead: bool


type Grid = list[list[Slot | None]]


@dataclass(frozen=True, slots=True)
class TableView:
    """A cleaned table in one label language.

    Attributes:
        layout (TableLayout): ``grid`` for a Markdown table, ``form`` for ``label: value``
            lines.
        header (list[str]): Combined header, one entry per column; empty when there is none.
        rows (list[list[str]]): Body rows, one entry per column.
        lines (list[list[tuple[str, bool]]]): For forms, each row's distinct non-empty cells
            as (text, is_value) pairs.
        unit (UnitStatement | None): Unit statement found in the table.
        truncated (bool): Whether rows were cut because the grid was too large.
    """

    layout: TableLayout
    header: list[str]
    rows: list[list[str]]
    lines: list[list[tuple[str, bool]]]
    unit: UnitStatement | None
    truncated: bool = False


def expand(table: Table) -> Grid:
    """Expand row and column spans into a rectangular grid.

    Args:
        table (Table): Table as written.

    Returns:
        Grid: One list per row; positions no cell covers are None. Rows after the grid
            reaches :data:`MAX_GRID_SLOTS` positions are left out.
    """
    limit = len(table.rows)
    taken: dict[tuple[int, int], Slot] = {}
    width = height = 0
    for row_index, row in enumerate(table.rows):
        if len(taken) > MAX_GRID_SLOTS or row_index * width > MAX_GRID_SLOTS:
            break
        column = 0
        for cell in row:
            while (row_index, column) in taken:
                column += 1
            _place(taken, cell, (row_index, column), height=limit)
            column += cell.colspan
        width = max(width, min(column, _MAX_WIDTH))
        height = row_index + 1
    return [[taken.get((r, c)) for c in range(width)] for r in range(height)]


def _place(
    taken: dict[tuple[int, int], Slot], cell: Cell, at: tuple[int, int], *, height: int
) -> None:
    """Mark the grid positions a cell covers.

    Args:
        taken (dict[tuple[int, int], Slot]): Covered positions so far.
        cell (Cell): Cell to place.
        at (tuple[int, int]): Top-left row and column.
        height (int): Number of rows; spans past the last row are cut.
    """
    row, column = at
    for row_offset in range(min(cell.rowspan, height - row)):
        for column_offset in range(min(cell.colspan, _MAX_WIDTH - column)):
            taken[row + row_offset, column + column_offset] = Slot(cell, column_offset == 0)


def view(table: Table, mode: LabelMode) -> TableView:
    """Clean a table and choose its layout.

    Args:
        table (Table): Table as written.
        mode (LabelMode): Label language for cell text.

    Returns:
        TableView: The cleaned table.
    """
    expanded = expand(table)
    cut = len(expanded) < len(table.rows)
    grid, texts = _clean(_drop_span_columns(expanded), mode)
    unit = _unit_of(table)
    heads = _header_count(grid)
    if heads == 0 and _is_form(grid, texts):
        return TableView("form", [], texts, [_form_line(row, mode) for row in grid], unit, cut)
    if heads == 0 and _first_row_is_header(grid):
        return TableView("grid", texts[0], texts[1:], [], unit, cut)
    header_rows = [[_text(slot, mode, repeat=True) for slot in row] for row in grid[:heads]]
    return TableView("grid", _combine(header_rows), texts[heads:], [], unit, cut)


def _clean(grid: Grid, mode: LabelMode) -> tuple[Grid, list[list[str]]]:
    """Drop fully empty rows and columns.

    Args:
        grid (Grid): Expanded grid.
        mode (LabelMode): Label language for cell text.

    Returns:
        tuple[Grid, list[list[str]]]: The kept grid positions and their texts.
    """
    texts = [[_text(slot, mode) for slot in row] for row in grid]
    rows = [index for index, row in enumerate(texts) if any(row)]
    width = len(grid[0]) if grid else 0
    columns = [c for c in range(width) if any(texts[r][c] for r in rows)]
    return (
        [[grid[r][c] for c in columns] for r in rows],
        [[texts[r][c] for c in columns] for r in rows],
    )


def _text(slot: Slot | None, mode: LabelMode, *, repeat: bool = False) -> str:
    """Return a grid position's text; column-span copies are blank unless repeated.

    Args:
        slot (Slot | None): Grid position.
        mode (LabelMode): Label language.
        repeat (bool): Whether column-span copies repeat the text (header rows).

    Returns:
        str: Cell text, or an empty string.
    """
    if slot is None or not (slot.lead or repeat) or is_unit_only(slot.cell.label.ko):
        return ""
    return slot.cell.label.text(mode)


def _drop_span_columns(grid: Grid) -> Grid:
    """Drop columns in which every row continues the previous column's span.

    Args:
        grid (Grid): Expanded grid.

    Returns:
        Grid: Grid without pure span-copy columns.
    """
    width = len(grid[0]) if grid else 0
    keep = [0, *(c for c in range(1, width) if not all(_continues(row, c) for row in grid))]
    return [[row[c] for c in keep] for row in grid] if width else grid


def _continues(row: list[Slot | None], column: int) -> bool:
    """Report whether a position copies the cell of the position to its left.

    Args:
        row (list[Slot | None]): Grid row.
        column (int): Column index, at least 1.

    Returns:
        bool: True for a column-span copy or a gap next to a gap.
    """
    slot, left = row[column], row[column - 1]
    if slot is None:
        return left is None
    return left is not None and not slot.lead and slot.cell is left.cell


def _unit_of(table: Table) -> UnitStatement | None:
    """Find the first unit statement in a table's cells.

    Args:
        table (Table): Table as written.

    Returns:
        UnitStatement | None: The statement, or None.
    """
    for row in table.rows:
        for cell in row:
            statement = find_unit_statement(cell.label.ko)
            if statement is not None:
                return statement
    return None


def _header_count(grid: Grid) -> int:
    """Count leading rows made only of header cells.

    Args:
        grid (Grid): Cleaned grid.

    Returns:
        int: Number of header rows.
    """
    count = 0
    for row in grid:
        cells = [slot.cell for slot in row if slot is not None]
        if not cells or not all(cell.header for cell in cells):
            break
        count += 1
    return min(count, max(len(grid) - 1, 1)) if count else 0


def _first_row_is_header(grid: Grid) -> bool:
    """Guess that a header-less table's first row is its header.

    Free-form DART tables often use ordinary cells for the header row; KRX tables and value
    rows do not qualify.

    Args:
        grid (Grid): Cleaned grid.

    Returns:
        bool: True when the first row has two or more distinct label cells and no values.
    """
    if len(grid) < _MIN_ROWS_WITH_HEADER:
        return False
    cells = _distinct(grid[0])
    return len(cells) >= _MIN_HEADER_CELLS and not any(cell.value for cell in cells)


def _distinct(row: list[Slot | None]) -> list[Cell]:
    """List a row's distinct cells in order.

    Args:
        row (list[Slot | None]): Grid row.

    Returns:
        list[Cell]: Cells, each once.
    """
    cells: list[Cell] = []
    for slot in row:
        if slot is not None and not any(slot.cell is cell for cell in cells):
            cells.append(slot.cell)
    return cells


def _is_form(grid: Grid, texts: list[list[str]]) -> bool:
    """Decide whether a header-less table reads best as ``label: value`` lines.

    Args:
        grid (Grid): Cleaned grid.
        texts (list[list[str]]): Cell texts of the cleaned grid.

    Returns:
        bool: True for layout and key/value tables.
    """
    rows = [_filled(row, text) for row, text in zip(grid, texts, strict=True)]
    if any(cell.value for row in rows for cell in row):
        return all(_form_row(row) for row in rows)
    return all(len(row) <= _FORM_MAX_CELLS for row in rows)


def _filled(row: list[Slot | None], texts: list[str]) -> list[Cell]:
    """List a row's distinct cells that have text at their lead position.

    Args:
        row (list[Slot | None]): Grid row.
        texts (list[str]): Texts of the row's positions.

    Returns:
        list[Cell]: Non-empty cells, each once, in order.
    """
    cells: list[Cell] = []
    for slot, text in zip(row, texts, strict=True):
        if slot is not None and text and not any(slot.cell is cell for cell in cells):
            cells.append(slot.cell)
    return cells


def _form_row(cells: list[Cell]) -> bool:
    """Check that a row of a value-marked table is a label/value row, not a data row.

    Args:
        cells (list[Cell]): The row's distinct non-empty cells.

    Returns:
        bool: False for header-like rows (three or more labels) and runs of more than two
            values.
    """
    if len(cells) >= _FORM_MAX_CELLS and not any(cell.value for cell in cells):
        return False
    run = longest = 0
    for cell in cells:
        if _is_connector(cell):
            continue
        run = run + 1 if cell.value else 0
        longest = max(longest, run)
    return longest <= _FORM_MAX_VALUE_RUN


def _is_connector(cell: Cell) -> bool:
    """Report whether a label cell only joins values, such as ``~`` between two dates.

    Args:
        cell (Cell): Cell to test.

    Returns:
        bool: True for short punctuation-only label cells.
    """
    return not cell.value and bool(_CONNECTOR.fullmatch(cell.label.ko))


def _form_line(row: list[Slot | None], mode: LabelMode) -> list[tuple[str, bool]]:
    """List a row's distinct non-empty cells as (text, is_value) pairs.

    Args:
        row (list[Slot | None]): Grid row.
        mode (LabelMode): Label language.

    Returns:
        list[tuple[str, bool]]: Cells in order; connectors count as values.
    """
    pairs: list[tuple[str, bool]] = []
    for cell in _distinct(row):
        value = cell.value or _is_connector(cell)
        label = cell.label if value else _strip_colon(cell.label)
        text = "" if is_unit_only(cell.label.ko) else label.text(mode)
        if text:
            pairs.append((text, value))
    return pairs


def _strip_colon(label: Label) -> Label:
    """Remove trailing colons from both languages of a label cell.

    Args:
        label (Label): Label cell text.

    Returns:
        Label: The label without trailing colons, so ``both`` renders ``Name (이름)``.
    """
    english = _LABEL_END.sub("", label.en) if label.en else None
    return Label(_LABEL_END.sub("", label.ko), english)


def _combine(header_rows: list[list[str]]) -> list[str]:
    """Combine stacked header rows into one label per column.

    Args:
        header_rows (list[list[str]]): Header row texts, with spans repeated.

    Returns:
        list[str]: One label per column, parts joined with `` / ``.
    """
    if not header_rows:
        return []
    combined: list[str] = []
    for column in zip(*header_rows, strict=True):
        parts: list[str] = []
        for text in column:
            if text and (not parts or parts[-1] != text):
                parts.append(text)
        combined.append(" / ".join(parts))
    return combined


def markdown_grid(header: list[str], rows: list[list[str]]) -> tuple[str, list[str]]:
    """Render a grid as a Markdown header block and one line per body row.

    Args:
        header (list[str]): Column labels; an empty list renders a blank header row.
        rows (list[list[str]]): Body rows.

    Returns:
        tuple[str, list[str]]: Header and separator lines, and the body row lines.
    """
    width = max([len(header), *(len(row) for row in rows)])
    labels = header or [""] * width
    head = _markdown_row(labels) + "\n" + "| " + " | ".join(["---"] * width) + " |"
    return head, [_markdown_row(row) for row in rows]


def _markdown_row(cells: list[str]) -> str:
    """Render one Markdown table row, escaping pipes and line breaks.

    Args:
        cells (list[str]): Cell texts.

    Returns:
        str: The row line.
    """
    escaped = (cell.replace("|", "\\|").replace("\n", "<br>") for cell in cells)
    return "| " + " | ".join(escaped) + " |"


def form_lines(lines: list[list[tuple[str, bool]]]) -> list[str]:
    """Render form rows as ``- label: value`` list items.

    Labels before a value form a path joined with `` / ``; several label/value pairs in one
    row are joined with ``; ``. Value lines after the first are indented under the item.

    Args:
        lines (list[list[tuple[str, bool]]]): Each row's (text, is_value) cells.

    Returns:
        list[str]: One list item per non-empty row.
    """
    rendered: list[str] = []
    for cells in lines:
        if cells:
            text = "; ".join(_pair_text(labels, values) for labels, values in _pairs(cells))
            rendered.append("- " + text.replace("\n", "\n  "))
    return rendered


def _pairs(cells: list[tuple[str, bool]]) -> list[tuple[list[str], list[str]]]:
    """Group a row's cells into (labels, values) pairs.

    Rows without any value cell treat the first cell as the label and the rest as values.
    Labels after the last value, such as ``부터`` (from) after a date, join that value.

    Args:
        cells (list[tuple[str, bool]]): The row's (text, is_value) cells.

    Returns:
        list[tuple[list[str], list[str]]]: Label path and values for each pair.
    """
    if not any(is_value for _, is_value in cells):
        return [([cells[0][0]], [text for text, _ in cells[1:]])]
    pairs: list[tuple[list[str], list[str]]] = []
    for text, is_value in cells:
        if not pairs or (not is_value and pairs[-1][1]):
            pairs.append(([], []))
        pairs[-1][1 if is_value else 0].append(text)
    if len(pairs) > 1 and not pairs[-1][1]:
        trailing = pairs.pop()[0]
        pairs[-1][1].extend(trailing)
    return pairs


def _pair_text(labels: list[str], values: list[str]) -> str:
    """Render one label/value pair.

    Args:
        labels (list[str]): Label path.
        values (list[str]): Values.

    Returns:
        str: ``label / sublabel: value``, or whichever side is present.
    """
    label = " / ".join(_LABEL_END.sub("", text).replace("\n", " ") for text in labels)
    value = " ".join(values)
    if label and value:
        return f"{label}: {value}"
    return label or value
