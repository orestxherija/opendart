"""Event report rows grouped into one record per filing, or per tranche of a debt offering.

Major-issue services return one row per decision. Securities-registration services return
sections ("General matters", "Securities class", ...) whose rows share a filing number, so
rows are grouped by filing number into one record. A debt registration statement can offer
several tranches (series such as 301-1 and 301-2) in one filing: it then has one General
matters row per tranche, and every section repeats the tranche's ordinal (``tm``), so such
a filing becomes one record per tranche, each with its own rows and the rows that name no
tranche. OpenDART folds amendments into the row of the original decision: the row carries
the latest filing number and the amended terms, and the date window of the query applies to
the original filing date.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel

from opendart_mcp.domain.identifiers import is_filing_number
from opendart_mcp.domain.normalize import clean_text
from opendart_mcp.events.values import normalize
from opendart_mcp.registry import EVENT_KINDS, field_kind, field_spec, service

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from opendart_mcp.events.values import Scalar
    from opendart_mcp.registry import EventKind, ServiceSpec

COMMON_FIELDS: Final = frozenset(
    {"filing_number", "corporation_type", "corporation_code", "corporation_name"}
)
"""Identity fields present on every row; results carry them once, elsewhere."""
TRANCHE_FIELD: Final = "tm"
"""Ordinal (series) that registration-statement sections repeat for each tranche."""


@dataclass(frozen=True, slots=True)
class Row:
    """One upstream row.

    Attributes:
        section (str): Catalog section title for registration statements; empty otherwise.
        values (Mapping[str, str]): Raw values keyed by SDK field name.
    """

    section: str
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Every row of one filing (or one tranche of a debt offering) for one event kind.

    Attributes:
        kind (EventKind): Event kind the rows came from.
        filing_number (str): Latest filing number of the event.
        rows (tuple[Row, ...]): Rows in upstream order.
    """

    kind: EventKind
    filing_number: str
    rows: tuple[Row, ...]

    @property
    def service(self) -> str:
        """SDK method name of the event kind's service.

        Returns:
            str: Service name, such as cvbd_is_decsn.
        """
        return EVENT_KINDS[self.kind].service

    def raw(self, name: str) -> str | None:
        """Return a field's first non-blank value across rows.

        Args:
            name (str): SDK field name.

        Returns:
            str | None: Cleaned text, or None when every row is blank or a dash.
        """
        for row in self.rows:
            value = clean_text(row.values.get(name))
            if value is not None:
                return value
        return None

    def value(self, name: str) -> Scalar:
        """Return a field's first value, normalized by its registry kind.

        Args:
            name (str): SDK field name.

        Returns:
            Scalar: Normalized value.
        """
        return normalize(field_kind(self.service, name), self.raw(name))


def _items(response: object, path: tuple[str, ...]) -> Iterator[tuple[str | None, object]]:
    """Walk the record containers of a response.

    Args:
        response (object): SDK response model.
        path (tuple[str, ...]): Record path from the registry: ("list",) or
            ("group", "list").

    Yields:
        tuple[str | None, object]: Section title from the response (None without groups)
            and the record model.
    """
    if path[0] != "group":
        for item in getattr(response, "list", None) or ():
            yield None, item
        return
    for group in getattr(response, "group", None) or ():
        for item in getattr(group, "list", None) or ():
            yield getattr(group, "title", None), item


def _values(spec: ServiceSpec, item: object) -> dict[str, str]:
    """Read a record's raw values by SDK field name.

    Undocumented upstream fields keep their upstream names.

    Args:
        spec (ServiceSpec): Service of the record.
        item (object): SDK record model.

    Returns:
        dict[str, str]: Non-null values as text.
    """
    data: dict[str, object] = item.model_dump() if isinstance(item, BaseModel) else {}
    values: dict[str, str] = {}
    for key, value in data.items():
        if value is not None:
            field = field_spec(spec, key)
            values[field.name if field else key] = value if isinstance(value, str) else str(value)
    return values


def _section(spec: ServiceSpec, title: str | None, values: Mapping[str, str]) -> str:
    """Match a response section to a catalog section.

    Upstream titles mostly match the catalog ("General matters"), but some differ ("Fund
    use purposes" for "Purpose of use of funds"); those are matched by their fields.

    Args:
        spec (ServiceSpec): Service of the record.
        title (str | None): Section title in the response.
        values (Mapping[str, str]): Raw values of the row.

    Returns:
        str: Catalog section title, or an empty string for services without sections.
    """
    sections = [record for record in spec.records if record.section]
    if not sections:
        return ""
    wanted = (title or "").strip().casefold()
    exact = next((r.section for r in sections if r.section.casefold() == wanted), None)
    if exact is not None:
        return exact
    keys = set(values) - COMMON_FIELDS
    return max(sections, key=lambda r: len(keys & {f.name for f in r.fields})).section


def _tranche(row: Row) -> str | None:
    """Read the tranche ordinal of a row in a comparable form.

    Args:
        row (Row): Upstream row.

    Returns:
        str | None: Ordinal without spaces, case, or the Korean 제/회 wrapper, such as
            "301-1"; None when the row names no tranche.
    """
    text = clean_text(row.values.get(TRANCHE_FIELD))
    if text is None:
        return None
    return "".join(text.split()).casefold().removeprefix("제").removesuffix("회")


def _tranches(record: EventRecord, *, lead: str) -> list[EventRecord]:
    """Split a registration statement that offers several tranches into one record each.

    The lead section (General matters) has one row per tranche. A tranche's record holds its
    own rows and every row that names no tranche, or one the lead section does not list.

    Args:
        record (EventRecord): Every row of one filing.
        lead (str): Section with one row per tranche; empty for services without sections.

    Returns:
        list[EventRecord]: One record per tranche in filed order, or the record itself
            when it has fewer than two tranches.
    """
    tagged = [(row, _tranche(row)) for row in record.rows]
    keys = dict.fromkeys(tag for row, tag in tagged if tag is not None and row.section == lead)
    if not lead or len(keys) <= 1:
        return [record]
    return [
        replace(record, rows=tuple(row for row, tag in tagged if tag == key or tag not in keys))
        for key in keys
    ]


def records_from(kind: EventKind, response: object) -> list[EventRecord]:
    """Group a response's rows into one record per filing number, or per tranche.

    Args:
        kind (EventKind): Event kind the response answers.
        response (object): SDK response model.

    Returns:
        list[EventRecord]: Records in upstream order; rows without a valid filing number
            are skipped, and a debt offering of several tranches gives one record each.
    """
    spec = service(EVENT_KINDS[kind].service)
    grouped: dict[str, list[Row]] = {}
    for title, item in _items(response, spec.records[0].path):
        values = _values(spec, item)
        number = (values.get("filing_number") or "").strip()
        if is_filing_number(number):
            grouped.setdefault(number, []).append(Row(_section(spec, title, values), values))
    lead = spec.records[0].section
    return [
        record
        for number, rows in grouped.items()
        for record in _tranches(EventRecord(kind, number, tuple(rows)), lead=lead)
    ]
