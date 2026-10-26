"""Describe event records: headline, key terms, schedule dates, flags, and labeled fields.

PRESENTATIONS holds one handwritten Presentation per EventKind; importing this module fails
when a kind has none, and a test checks that every field a presentation names exists in the
kind's service.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_analysis.catalog import EVENT_KINDS, field_spec
from opendart_analysis.domain.normalize import clean_text
from opendart_analysis.events.dates import board_date, event_dates
from opendart_analysis.events.flags import event_flags
from opendart_analysis.events.kinds_capital import CAPITAL
from opendart_analysis.events.kinds_deals import DEALS
from opendart_analysis.events.kinds_other import OTHER
from opendart_analysis.events.records import COMMON_FIELDS
from opendart_analysis.events.templates import headline, key_terms
from opendart_analysis.events.values import normalize

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from opendart_analysis.catalog import EventGroup, EventKind
    from opendart_analysis.events.records import EventRecord
    from opendart_analysis.events.templates import Presentation
    from opendart_analysis.events.values import Scalar

_ALL: Final = {**CAPITAL, **DEALS, **OTHER}
PRESENTATIONS: Final[Mapping[EventKind, Presentation]] = MappingProxyType(
    {kind: _ALL[kind] for kind in EVENT_KINDS}
)
"""Presentation of every event kind, in catalog order."""


@dataclass(frozen=True, slots=True)
class EventView:
    """An event report reduced to what an analyst reads first.

    Attributes:
        kind (EventKind): Event kind.
        group (EventGroup): Group of the kind.
        label (str): Short English name of the kind.
        filing_number (str): Latest filing number of the event.
        headline (str): One-line summary.
        key_terms (Mapping[str, Scalar]): Concise normalized terms.
        dates (tuple[tuple[str, date], ...]): (action code, date) pairs in date order.
        flags (tuple[str, ...]): Flags raised by the report.
        board_date (date | None): Board resolution date, when the report has one.
    """

    kind: EventKind
    group: EventGroup
    label: str
    filing_number: str
    headline: str
    key_terms: Mapping[str, Scalar]
    dates: tuple[tuple[str, date], ...]
    flags: tuple[str, ...]
    board_date: date | None


@dataclass(frozen=True, slots=True)
class LabeledValue:
    """One filled field of a report with its catalog label.

    Attributes:
        name (str): SDK field name.
        label (str): Catalog label.
        value (Scalar): Normalized value.
        raw (str): Value as filed, whitespace collapsed.
        section (str): Registration-statement section; empty for other reports.
    """

    name: str
    label: str
    value: Scalar
    raw: str
    section: str


def describe(record: EventRecord) -> EventView:
    """Summarize one event record.

    Args:
        record (EventRecord): Event rows.

    Returns:
        EventView: Headline, key terms, dates, flags, and board date.
    """
    presentation = PRESENTATIONS[record.kind]
    return EventView(
        kind=record.kind,
        group=EVENT_KINDS[record.kind].group,
        label=presentation.label,
        filing_number=record.filing_number,
        headline=headline(presentation, record),
        key_terms=key_terms(presentation, record),
        dates=event_dates(record),
        flags=event_flags(record),
        board_date=board_date(record),
    )


def labeled_fields(record: EventRecord) -> tuple[LabeledValue, ...]:
    """List every filled field of a record with its label, in row order.

    Identity fields repeated on every row and blank or dash values are left out.

    Args:
        record (EventRecord): Event rows.

    Returns:
        tuple[LabeledValue, ...]: Labeled values.
    """
    found: list[LabeledValue] = []
    for row in record.rows:
        for name, raw in row.values.items():
            text = clean_text(raw)
            if text is None or name in COMMON_FIELDS:
                continue
            spec = field_spec(record.service, name, section=row.section or None)
            label, kind = (spec.label, spec.kind) if spec else (name, "text")
            found.append(LabeledValue(name, label, normalize(kind, text), text, row.section))
    return tuple(found)
