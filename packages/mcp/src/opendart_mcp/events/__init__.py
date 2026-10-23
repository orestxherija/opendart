"""Event semantics for get_corporate_events and the corporate-action calendar.

A pure layer over the registry: it groups upstream rows into one record per filing
(records), normalizes values by field kind (values), names schedule dates (dates) and flags
(flags), maps filing titles to event kinds (titles), and summarizes each kind with a
handwritten presentation (templates, kinds_*, catalog).
"""

from __future__ import annotations

from opendart_mcp.events.catalog import (
    PRESENTATIONS,
    EventView,
    LabeledValue,
    describe,
    labeled_fields,
)
from opendart_mcp.events.dates import ACTIONS, CALENDAR_KINDS, Action, board_date, event_dates
from opendart_mcp.events.flags import AMENDED, FLAG_FIELDS, POSSIBLY_AMENDED, event_flags
from opendart_mcp.events.records import EventRecord, Row, records_from
from opendart_mcp.events.titles import kind_for_title
from opendart_mcp.events.values import Scalar, normalize, parse_flag, parse_span

__all__ = [
    "ACTIONS",
    "AMENDED",
    "CALENDAR_KINDS",
    "FLAG_FIELDS",
    "POSSIBLY_AMENDED",
    "PRESENTATIONS",
    "Action",
    "EventRecord",
    "EventView",
    "LabeledValue",
    "Row",
    "Scalar",
    "board_date",
    "describe",
    "event_dates",
    "event_flags",
    "kind_for_title",
    "labeled_fields",
    "normalize",
    "parse_flag",
    "parse_span",
    "records_from",
]
