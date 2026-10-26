"""Read one company's event reports for the calendar, over the windows ``Reads`` plans.

When the filing index picks the kinds, one search over the extended window serves both
windows, so the longer window costs no extra search: a kind outside ``LONG_KINDS`` is read
only when the index lists one of its filings since the recent window's start, and every
kind of a group the index could not read in full counts as filed. Requested kinds skip the
index; an empty request reads nothing.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from opendart_analysis.calendar.lookback import LONG_KINDS, RECENT_KINDS
from opendart_analysis.catalog import EVENT_KINDS
from opendart_analysis.domain.identifiers import filing_date
from opendart_analysis.events import DEFAULT_POLICY, EventQuery, fetch_events, search_index
from opendart_analysis.events.index import GROUP_RESOURCES
from opendart_analysis.extracts import gather_all

if TYPE_CHECKING:
    from opendart_analysis.calendar.lookback import Reads
    from opendart_analysis.catalog import EventKind
    from opendart_analysis.events import EventBatch, EventIndex, ReadPolicy
    from opendart_analysis.filings import ReadFilingPage
    from opendart_analysis.upstream import FetchService


def filed_since(index: EventIndex, since: date) -> frozenset[EventKind]:
    """List the kinds that the filing index shows filed since a date.

    Every kind of a group the index could not read in full counts as filed, as when events
    are read without requested kinds.

    Args:
        index (EventIndex): Filing index.
        since (date): First filing date.

    Returns:
        frozenset[EventKind]: Kinds to read.
    """
    resources = {GROUP_RESOURCES[group] for group in index.incomplete}
    partial = {kind for kind, spec in EVENT_KINDS.items() if spec.resource in resources}
    dated = {
        kind
        for filing in index.filings
        if (kind := filing.kind) is not None
        and (filing_date(filing.filing_number) or date.min) >= since
    }
    return frozenset(partial | dated)


def indexed_kinds(
    index: EventIndex, reads: Reads
) -> tuple[tuple[EventKind, ...], tuple[EventKind, ...]]:
    """Pick the kinds to read from a filing index searched over the extended window.

    Args:
        index (EventIndex): Filing index of the extended window.
        reads (Reads): Windows to read.

    Returns:
        tuple[tuple[EventKind, ...], tuple[EventKind, ...]]: Kinds filed since the recent
            window's start, and LONG_KINDS filed since the extended window's start, each in
            catalog order.
    """
    recent, seen = filed_since(index, reads.recent.start), index.kinds
    return (
        tuple(k for k in EVENT_KINDS if k in recent and k in RECENT_KINDS),
        tuple(k for k in EVENT_KINDS if k in seen and k in LONG_KINDS),
    )


async def read_events(
    corp_code: str,
    reads: Reads,
    *,
    fetch_service: FetchService,
    read_filing_page: ReadFilingPage,
    policy: ReadPolicy = DEFAULT_POLICY,
) -> list[EventBatch]:
    """Read one company's event reports: LONG_KINDS over the extended window, others recently.

    Args:
        corp_code (str): DART corporation code.
        reads (Reads): What to read.
        fetch_service (FetchService): Calls event services; failures that
            ``policy.tolerate`` accepts become failed kinds, others propagate unchanged.
        read_filing_page (ReadFilingPage): Reads the filing index when ``reads.kinds`` is
            None, up to ``policy.max_index_pages`` pages per group.
        policy (ReadPolicy): Failure tolerance, concurrency, and index page limit.

    Returns:
        list[EventBatch]: One batch per window read, recent first; empty when no kind is
            read.
    """
    if reads.kinds is None:
        index = await search_index(
            corp_code, reads.extended, read_page=read_filing_page, max_pages=policy.max_index_pages
        )
        recent, extended = indexed_kinds(index, reads)
    else:
        recent = tuple(kind for kind in reads.kinds if kind not in LONG_KINDS)
        extended = tuple(kind for kind in reads.kinds if kind in LONG_KINDS)
    windows = ((reads.recent, recent), (reads.extended, extended))
    return await gather_all(
        fetch_events(
            EventQuery(corp_code, window, kinds=kinds),
            fetch_service=fetch_service,
            read_filing_page=read_filing_page,
            policy=policy,
        )
        for window, kinds in windows
        if kinds
    )
