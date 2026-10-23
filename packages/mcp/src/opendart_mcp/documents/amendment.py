"""Amendment summaries from the correction section of an amended filing.

DART amendments open with a ``정 정 신 고 (보고)`` section naming the corrected document and its
original filing date, followed by an item / reason / before / after table. Corrected KRX
pages carry the same facts in a ``정정신고(보고)`` block ahead of the form, with one overall
reason and item / before / after rows.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from opendart_mcp.documents.models import Amendment, AmendmentChange
from opendart_mcp.documents.tables import view
from opendart_mcp.documents.tree import Paragraph, Section, Table, compact, walk_sections

if TYPE_CHECKING:
    from opendart_mcp.documents.tree import Block, DocumentTree

_CORRECTION = "정정신고"
_DATE = re.compile(r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})")
_MAX_TEXT = 600
_FIELDS = (
    ("original_filed", ("제출일",)),
    ("corrected_document", ("정정대상공시서류", "정정관련공시서류")),
    ("reason", ("정정사유",)),
)


def extract_amendment(tree: DocumentTree) -> Amendment | None:
    """Summarize the correction section of an amended filing.

    Args:
        tree (DocumentTree): Parsed main document.

    Returns:
        Amendment | None: The summary, or None when the document is not an amendment.
    """
    found = _correction_tables(tree)
    if found is None:
        return None
    section_id, tables = found
    fields: dict[str, str] = {}
    changes: list[AmendmentChange] = []
    for table in tables:
        _scan(table, fields, changes)
    reason = fields.get("reason")
    return Amendment(
        original_filed=_iso_date(fields["original_filed"]) if "original_filed" in fields else None,
        corrected_document=fields.get("corrected_document"),
        reason=reason,
        section_id=section_id,
        changes=[
            change if change.reason else change.model_copy(update={"reason": reason})
            for change in changes
        ],
    )


def _correction_tables(tree: DocumentTree) -> tuple[str, list[Table]] | None:
    """Find the correction section and its tables.

    Args:
        tree (DocumentTree): Parsed main document.

    Returns:
        tuple[str, list[Table]] | None: Section ID and tables, or None.
    """
    for section in walk_sections(tree.items):
        if section.kind == "correction" or compact(section.title.ko).startswith(_CORRECTION):
            return section.id, _tables(section.items)
        if section.kind == "body":
            tables = _krx_block(section.items)
            return (section.id, tables) if tables else None
    return None


def _tables(items: tuple[Block | Section, ...]) -> list[Table]:
    """List tables among items and their subsections.

    Args:
        items (tuple[Block | Section, ...]): Items to search.

    Returns:
        list[Table]: Tables in document order.
    """
    found: list[Table] = []
    for item in items:
        if isinstance(item, Table):
            found.append(item)
        elif isinstance(item, Section):
            found.extend(_tables(item.items))
    return found


def _krx_block(items: tuple[Block | Section, ...]) -> list[Table]:
    """Collect the tables of a KRX correction block, which ends at the bold form title.

    Args:
        items (tuple[Block | Section, ...]): Items of the KRX body section.

    Returns:
        list[Table]: Tables of the correction block; empty when the page has none.
    """
    tables: list[Table] = []
    started = False
    for item in items:
        if isinstance(item, Paragraph):
            if started and all(run.bold for run in item.runs):
                break
            started = started or compact(item.plain).startswith(_CORRECTION)
        elif started and isinstance(item, Table):
            tables.append(item)
    return tables


def _scan(table: Table, fields: dict[str, str], changes: list[AmendmentChange]) -> None:
    """Read labeled fields and change rows from one table.

    Args:
        table (Table): Table of the correction section.
        fields (dict[str, str]): Fields found so far, updated in place.
        changes (list[AmendmentChange]): Changes found so far, extended in place.
    """
    shown = view(table, "korean")
    rows = [shown.header, *shown.rows] if shown.header else shown.rows
    columns: dict[str, int] | None = None
    for row in rows:
        if columns is None:
            columns = _change_columns(row)
            if columns is None:
                _field(row, fields)
        else:
            change = _change(row, columns)
            if change is not None:
                changes.append(change)


def _field(row: list[str], fields: dict[str, str]) -> None:
    """Record a labeled field such as the original filing date.

    Args:
        row (list[str]): Row texts.
        fields (dict[str, str]): Fields found so far, updated in place.
    """
    cells = [text for text in row if text]
    if len(cells) < 2:  # noqa: PLR2004 - a field is a label and a value
        return
    label = compact(cells[0])
    for name, keys in _FIELDS:
        if name not in fields and any(key in label for key in keys):
            fields[name] = cells[1]
            return


def _change_columns(row: list[str]) -> dict[str, int] | None:
    """Locate the item, reason, before, and after columns of a change header row.

    Args:
        row (list[str]): Row texts.

    Returns:
        dict[str, int] | None: Column index by role, or None when the row is not a header.
    """
    labels = [compact(text) for text in row]
    columns: dict[str, int] = {}
    for index, label in enumerate(labels):
        role = _role(label)
        if role is not None and role not in columns:
            columns[role] = index
    if "before" not in columns or "after" not in columns:
        return None
    columns.setdefault("item", 0)
    return columns


def _role(label: str) -> str | None:
    """Classify a change-table header label.

    Args:
        label (str): Compact header text.

    Returns:
        str | None: ``before``, ``after``, ``reason``, ``item``, or None.
    """
    if "정정전" in label:
        return "before"
    if "정정후" in label:
        return "after"
    if "사유" in label:
        return "reason"
    return "item" if "항목" in label else None


def _change(row: list[str], columns: dict[str, int]) -> AmendmentChange | None:
    """Build one change from a row of the change table.

    Args:
        row (list[str]): Row texts.
        columns (dict[str, int]): Column index by role.

    Returns:
        AmendmentChange | None: The change, or None for a blank row.
    """
    values = {
        role: _clip(row[index]) if index < len(row) else "" for role, index in columns.items()
    }
    if not any(values.values()):
        return None
    return AmendmentChange(
        item=values.get("item", ""),
        reason=values.get("reason") or None,
        before=values.get("before", ""),
        after=values.get("after", ""),
    )


def _clip(text: str) -> str:
    """Shorten long cell text for the summary.

    Args:
        text (str): Cell text.

    Returns:
        str: Text of at most about 600 characters.
    """
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT].rstrip() + "…"


def _iso_date(text: str) -> str:
    """Normalize a Korean or dotted date to ISO format.

    Args:
        text (str): Date such as ``2026년 10월 20일`` or ``2025.12.01``.

    Returns:
        str: ``YYYY-MM-DD``, or the text unchanged when it is not a date.
    """
    match = _DATE.search(text)
    if match is None:
        return text
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"
