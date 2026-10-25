"""Corporate events: interpreted major-issue and registration reports, and reading them.

A pure layer over the service catalog groups upstream rows into one record per filing, or per
tranche of a debt offering (records), normalizes values by field kind (values), names
schedule dates (dates) and flags (flags), maps filing titles to event kinds (titles), and
summarizes each kind with a handwritten presentation (templates, kinds_*, catalog).

``fetch_events`` reads a company's event reports in a window through caller-supplied data
access, choosing the services from the company's filing index (index):

    batch = await fetch_events(
        EventQuery("00126380", window),
        fetch_service=fetch_service,
        read_filing_page=read_filing_page,
    )
    views = [describe(record) for record in batch.records]

Data access follows ``opendart_analysis.upstream``. Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.events.catalog import (
    PRESENTATIONS,
    EventView,
    LabeledValue,
    describe,
    labeled_fields,
)
from opendart_analysis.events.dates import (
    ACTIONS,
    CALENDAR_KINDS,
    Action,
    board_date,
    event_dates,
)
from opendart_analysis.events.fetch import (
    DEFAULT_POLICY,
    EARLIEST,
    EventBatch,
    EventQuery,
    ReadPolicy,
    Strategy,
    covered_window,
    fetch_events,
    tolerate_data_source_errors,
)
from opendart_analysis.events.flags import (
    AMENDED,
    AMENDMENT_GAP_DAYS,
    FLAG_FIELDS,
    POSSIBLY_AMENDED,
    amendment_flag,
    event_flags,
)
from opendart_analysis.events.index import EventIndex, IndexedFiling, search_index
from opendart_analysis.events.records import EventRecord, Row, records_from
from opendart_analysis.events.titles import kind_for_title, plain_title
from opendart_analysis.events.values import Scalar, normalize, parse_flag, parse_span

__all__ = [
    "ACTIONS",
    "AMENDED",
    "AMENDMENT_GAP_DAYS",
    "CALENDAR_KINDS",
    "DEFAULT_POLICY",
    "EARLIEST",
    "FLAG_FIELDS",
    "POSSIBLY_AMENDED",
    "PRESENTATIONS",
    "Action",
    "DateWindow",
    "EventBatch",
    "EventIndex",
    "EventQuery",
    "EventRecord",
    "EventView",
    "IndexedFiling",
    "LabeledValue",
    "ReadPolicy",
    "Row",
    "Scalar",
    "Strategy",
    "amendment_flag",
    "board_date",
    "covered_window",
    "describe",
    "event_dates",
    "event_flags",
    "fetch_events",
    "kind_for_title",
    "labeled_fields",
    "normalize",
    "parse_flag",
    "parse_span",
    "plain_title",
    "records_from",
    "search_index",
    "tolerate_data_source_errors",
]
