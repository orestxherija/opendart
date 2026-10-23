"""Turn upstream service responses into labeled, normalized tables for call_service.

Responses nest records differently: most under ``list``, registration statements under
``group`` sections that each hold a ``list``, and the remuneration (Ver 2.0) services under
``group`` records with a nested ``list``. Flattening walks any of these shapes and merges
outer values into each inner record, so every row stands alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.identifiers import is_filing_number
from opendart_mcp.domain.normalize import (
    clean_text,
    market_from_corp_cls,
    parse_date,
    parse_decimal,
    parse_percent,
)
from opendart_mcp.domain.periods import PERIODS_BY_REPORT_CODE
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.services import ServiceColumn, ServiceTable
from opendart_mcp.registry import field_spec

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pydantic import BaseModel

    from opendart_mcp.models.services import Cell
    from opendart_mcp.registry import FieldKind, ServiceSpec

# Response envelope fields that are not data.
_ENVELOPE: Final = frozenset({"status", "message"})
_MAX_SOURCES: Final = 20
_PERIODS: Final[dict[str, str]] = {
    str(code): str(period) for code, period in PERIODS_BY_REPORT_CODE.items()
}


@dataclass(frozen=True, slots=True)
class Row:
    """One flattened record.

    Attributes:
        section (str): Registration-statement section title; empty for other services.
        values (dict[str, str]): Upstream strings by SDK field name.
    """

    section: str
    values: dict[str, str]


def _children(node: Mapping[str, object]) -> list[dict[str, object]]:
    """List the nested records of a node.

    Args:
        node (Mapping[str, object]): Dumped response or record.

    Returns:
        list[dict[str, object]]: Records from every list-valued field.
    """
    return [
        {str(key): value for key, value in item.items()}
        for value in node.values()
        if isinstance(value, list)
        for item in value
        if isinstance(item, dict)
    ]


def _walk(node: Mapping[str, object], inherited: dict[str, str], section: str) -> list[Row]:
    """Flatten a node, merging its values into every nested record.

    Args:
        node (Mapping[str, object]): Dumped response or record.
        inherited (dict[str, str]): Values from enclosing records.
        section (str): Section title from an enclosing group.

    Returns:
        list[Row]: Rows for the node's records, or one row for a leaf with values.
    """
    values = {key: value for key, value in node.items() if isinstance(value, str)}
    if "title" in values and any(isinstance(value, list) for value in node.values()):
        section = values.pop("title")
    children = _children(node)
    merged = inherited | values
    if not children:
        return [Row(section, merged)] if values else []
    return [row for child in children for row in _walk(child, merged, section)]


def flatten(response: BaseModel | None) -> list[Row]:
    """Flatten a service response into rows.

    Args:
        response (BaseModel | None): SDK response, or None for "no data".

    Returns:
        list[Row]: Rows in response order; empty when there is no data.
    """
    if response is None:
        return []
    data = response.model_dump()
    return _walk({k: v for k, v in data.items() if k not in _ENVELOPE}, {}, "")


def upstream_paging(response: BaseModel | None) -> str | None:
    """Explain upstream pages beyond the one returned, as for filing searches.

    Args:
        response (BaseModel | None): SDK response.

    Returns:
        str | None: A note when OpenDART reports more pages, else None.
    """
    total_pages = getattr(response, "total_page", None)
    number = getattr(response, "page_number", None)
    if not isinstance(total_pages, int) or not isinstance(number, int) or total_pages <= number:
        return None
    total = getattr(response, "total_count", None)
    return f"OpenDART reports {total} results over {total_pages} pages; pass page_no (and page_count up to 100) for upstream page {number + 1}."


def _number(text: str) -> int | float | None:
    """Parse a number, keeping whole numbers as integers.

    Args:
        text (str): Cleaned upstream text.

    Returns:
        int | float | None: The number, or None when the text is not one.
    """
    value = parse_decimal(text)
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _iso_date(text: str) -> str | None:
    """Parse a date into ISO form.

    Args:
        text (str): Cleaned upstream text.

    Returns:
        str | None: ISO date, or None when the text is not a date.
    """
    value = parse_date(text)
    return value.isoformat() if value else None


_PARSERS: Final[dict[str, Callable[[str], Cell]]] = {
    "amount": _number,
    "per_share": _number,
    "count": _number,
    "number": _number,
    "ratio": _number,
    "percent": parse_percent,
    "date": _iso_date,
}
_CODES: Final[dict[str, Callable[[str], Cell]]] = {
    "corp_cls": market_from_corp_cls,
    "reprt_code": _PERIODS.get,
}


@dataclass(frozen=True, slots=True)
class _Field:
    """A column with what normalization needs.

    Attributes:
        column (ServiceColumn): Published column.
        wire (str): Upstream field name.
    """

    column: ServiceColumn
    wire: str

    def normalize(self, text: str | None) -> Cell:
        """Normalize one upstream value by the field's kind.

        Args:
            text (str | None): Upstream text.

        Returns:
            Cell: Number, ISO date, market, period, or clean text; None when blank.
        """
        cleaned = clean_text(text)
        if cleaned is None:
            return None
        parse = _CODES.get(self.wire) or _PARSERS.get(self.column.kind)
        parsed = parse(cleaned) if parse else None
        return cleaned if parsed is None else parsed


def _fields(spec: ServiceSpec, section: str, records: list[dict[str, str]]) -> list[_Field]:
    """Collect a table's fields in order of appearance, labeled from the registry.

    Args:
        spec (ServiceSpec): Service.
        section (str): Section title, or empty.
        records (list[dict[str, str]]): Rows of the table.

    Returns:
        list[_Field]: Fields; undocumented ones are text labeled by name, and a repeated
            label is suffixed with the field name.
    """
    names = dict.fromkeys(name for record in records for name in record)
    found = {name: field_spec(spec, name, section=section or None) for name in names}
    labels = [entry.label if entry else name for name, entry in found.items()]
    fields: list[_Field] = []
    for (name, entry), label in zip(found.items(), labels, strict=True):
        kind: FieldKind = entry.kind if entry else "text"
        unique = f"{label} ({name})" if labels.count(label) > 1 else label
        column = ServiceColumn(name=name, label=unique, kind=kind)
        fields.append(_Field(column, entry.wire if entry else name))
    return fields


def _concise(section: str, fields: list[_Field], cells: list[list[Cell]]) -> ServiceTable:
    """Drop empty columns and list values shared by every row once.

    Args:
        section (str): Section title, or empty.
        fields (list[_Field]): Table fields.
        cells (list[list[Cell]]): Normalized values aligned with fields.

    Returns:
        ServiceTable: Compact table.
    """
    keep = [i for i in range(len(fields)) if any(row[i] is not None for row in cells)]
    shared = {i for i in keep if len(cells) > 1 and all(row[i] == cells[0][i] for row in cells)}
    varying = [i for i in keep if i not in shared]
    return ServiceTable(
        section=section or None,
        common={fields[i].column.label: cells[0][i] for i in keep if i in shared} or None,
        columns=[fields[i].column for i in varying],
        rows=[[row[i] for i in varying] for row in cells],
    )


def _table(
    spec: ServiceSpec, section: str, records: list[dict[str, str]], *, detailed: bool
) -> ServiceTable:
    """Build one table from rows of the same section.

    Args:
        spec (ServiceSpec): Service.
        section (str): Section title, or empty.
        records (list[dict[str, str]]): Rows of the section.
        detailed (bool): Keep every column and add the upstream text.

    Returns:
        ServiceTable: Labeled, normalized table.
    """
    fields = _fields(spec, section, records)
    raw = [[record.get(field.column.name) for field in fields] for record in records]
    cells = [
        [field.normalize(value) for field, value in zip(fields, row, strict=True)] for row in raw
    ]
    if not detailed:
        return _concise(section, fields, cells)
    columns = [field.column for field in fields]
    return ServiceTable(section=section or None, columns=columns, rows=cells, raw=raw)


def tables(spec: ServiceSpec, rows: list[Row], *, detailed: bool) -> list[ServiceTable]:
    """Group rows by section into labeled, normalized tables.

    Args:
        spec (ServiceSpec): Service.
        rows (list[Row]): Flattened rows.
        detailed (bool): Keep every column and add the upstream text.

    Returns:
        list[ServiceTable]: One table per section, in order of appearance.
    """
    sections: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        sections.setdefault(row.section, []).append(row.values)
    return [
        _table(spec, section, records, detailed=detailed) for section, records in sections.items()
    ]


def source_filings(rows: list[Row]) -> list[SourceFiling]:
    """Cite the distinct filings that rows come from.

    Args:
        rows (list[Row]): Rows shown.

    Returns:
        list[SourceFiling]: Up to 20 filings in order of appearance.
    """
    titles: dict[str, str | None] = {}
    for row in rows:
        number = (row.values.get("filing_number") or "").strip()
        if is_filing_number(number):
            titles.setdefault(number, clean_text(row.values.get("report_title")))
    return [SourceFiling.of(number, title) for number, title in list(titles.items())[:_MAX_SOURCES]]
