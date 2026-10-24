"""Shape a batch of event reports into the get_corporate_events result.

``opendart_analysis.events`` reads and interprets the reports; this module projects them
into the tool's output models and adds paging and notes written for the model.

Concise events carry the headline, key terms, dated actions, and flags; detailed events add
every filled field with its catalog label and the value as filed. Events are newest first,
cut to the requested limit with the exact call that fetches more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.identifiers import dart_viewer_url, filing_date
from opendart_analysis.events import (
    AMENDED,
    AMENDMENT_GAP_DAYS,
    POSSIBLY_AMENDED,
    amendment_flag,
    describe,
    labeled_fields,
    plain_title,
)
from opendart_mcp.models.common import NextCall, Pagination
from opendart_mcp.models.events import (
    CorporateEvent,
    CorporateEventsResult,
    EventCoverage,
    EventDate,
    EventField,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import JsonValue

    from opendart_analysis.events import EventBatch, EventRecord, LabeledValue
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import CompanyRef

DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 200
_UNSTRUCTURED_SHOWN: Final = 5
_UNREAD: Final = {
    "B": "The company has more major-issue filings in the window than the index reads, so every major-issue report was read.",
    "C": "The company has more offering filings in the window than the index reads, so every registration report was read.",
}
_FLAG_NOTES: Final = (
    (AMENDED, "Amended events show the latest terms; filed is the date of the latest correction."),
    (
        POSSIBLY_AMENDED,
        f"Events flagged possibly_amended were last filed more than {AMENDMENT_GAP_DAYS} days after the board resolution, which usually means a correction: they may show amended terms, and filed may be the correction date. search_filings lists each version.",
    ),
)
_TRANCHES: Final = (
    "Debt offerings with several tranches are listed once per tranche, under one filing number."
)


@dataclass(frozen=True, slots=True)
class EventRequest:
    """Validated arguments of get_corporate_events.

    Attributes:
        categories (tuple[str, ...] | None): Requested event groups or kinds.
        since (str | None): Window start as given.
        until (str | None): Window end as given.
        limit (int): Maximum events returned.
        detailed (bool): Whether to add every labeled field.
    """

    categories: tuple[str, ...] | None = None
    since: str | None = None
    until: str | None = None
    limit: int = DEFAULT_LIMIT
    detailed: bool = False


def _field(item: LabeledValue) -> EventField:
    """Convert a labeled value to its output model.

    Args:
        item (LabeledValue): Labeled report field.

    Returns:
        EventField: Output field; raw is kept only when it differs from the value.
    """
    same = isinstance(item.value, str) and item.value == item.raw
    return EventField(
        name=item.name,
        label=item.label,
        value=item.value,
        raw=None if same else item.raw,
        section=item.section or None,
    )


def event_model(
    record: EventRecord, *, titles: Mapping[str, str], detailed: bool = False
) -> CorporateEvent:
    """Describe one event record as an output model.

    Args:
        record (EventRecord): Event rows.
        titles (Mapping[str, str]): Filing index titles by filing number.
        detailed (bool): Whether to add every labeled field.

    Returns:
        CorporateEvent: The event.
    """
    view = describe(record)
    amendment = amendment_flag(view, titles)
    flags = [*view.flags, amendment] if amendment else list(view.flags)
    return CorporateEvent(
        kind=view.kind,
        group=view.group,
        filed=filing_date(view.filing_number),
        board_date=view.board_date,
        filing_number=view.filing_number,
        headline=view.headline,
        key_terms=dict(view.key_terms),
        dates=[EventDate(what=what, date=day) for what, day in view.dates],
        flags=flags or None,
        dart_url=dart_viewer_url(view.filing_number),
        fields=[_field(item) for item in labeled_fields(record)] if detailed else None,
    )


def _pagination(batch: EventBatch, request: EventRequest) -> Pagination | None:
    """Describe the events left out by the limit.

    Args:
        batch (EventBatch): Event reports read.
        request (EventRequest): Tool arguments.

    Returns:
        Pagination | None: Paging with the call that returns more, or None when every
            event fits.
    """
    total = len(batch.records)
    if total <= request.limit:
        return None
    next_call = None
    if request.limit < MAX_LIMIT:
        arguments: dict[str, JsonValue] = {
            "company": batch.corp_code,
            "since": batch.window.start.isoformat(),
            "until": batch.window.end.isoformat(),
            "limit": min(total, MAX_LIMIT),
        }
        if request.categories:
            categories: list[JsonValue] = [*request.categories]
            arguments["categories"] = categories
        if request.detailed:
            arguments["response_format"] = "detailed"
        next_call = NextCall(tool="get_corporate_events", arguments=arguments)
    return Pagination(total=total, page=1, limit=request.limit, has_more=True, next_call=next_call)


def _unstructured_note(batch: EventBatch) -> list[str]:
    """Point to major-issue filings that no structured report covers.

    Args:
        batch (EventBatch): Event reports read.

    Returns:
        list[str]: One note listing up to five titles with their latest filing numbers.
    """
    filings = batch.index.unstructured() if batch.index else ()
    latest: dict[str, str] = {}
    for filing in filings:
        latest.setdefault(plain_title(filing.title), filing.filing_number)
    if not latest:
        return []
    shown = "; ".join(f"{t} ({n})" for t, n in list(latest.items())[:_UNSTRUCTURED_SHOWN])
    more = len(latest) - _UNSTRUCTURED_SHOWN
    extra = f"; and {more} more titles" if more > 0 else ""
    return [
        f"Major-issue filings without a structured report (read them with read_filing): {shown}{extra}."
    ]


def _event_notes(events: list[CorporateEvent]) -> list[str]:
    """Explain amendment flags and tranches among the events returned.

    Args:
        events (list[CorporateEvent]): Events returned.

    Returns:
        list[str]: One note per amendment flag present, and one when a filing appears as
            several tranches.
    """
    flags = {flag for event in events for flag in event.flags or ()}
    notes = [note for flag, note in _FLAG_NOTES if flag in flags]
    if len({event.filing_number for event in events}) < len(events):
        notes.append(_TRANCHES)
    return notes


def _empty_note(batch: EventBatch) -> str:
    """Explain an empty result.

    Args:
        batch (EventBatch): Event reports read.

    Returns:
        str: Note naming the window.
    """
    span = f"{batch.window.start} to {batch.window.end}"
    if batch.strategy == "filing_index" and not batch.queried:
        return f"The company filed no major-issue or offering reports with structured data from {span}."
    return f"No events were found in the reports read for original filings from {span}."


def _notes(batch: EventBatch, events: list[CorporateEvent], request: EventRequest) -> list[str]:
    """Collect coverage, amendment, and truncation notes.

    Args:
        batch (EventBatch): Event reports read.
        events (list[CorporateEvent]): Events returned.
        request (EventRequest): Tool arguments.

    Returns:
        list[str]: Notes in reading order.
    """
    unread: list[str] = sorted(batch.index.incomplete) if batch.index else []
    notes = [_UNREAD[group] for group in unread]
    if batch.failed:
        notes.append(
            f"OpenDART did not answer for {", ".join(batch.failed)}; retry later for those kinds."
        )
    notes.extend(_unstructured_note(batch))
    notes.extend(_event_notes(events))
    total = len(batch.records)
    if not total:
        notes.append(_empty_note(batch))
    elif total > request.limit:
        notes.append(
            f"Showing the {request.limit} most recent of {total} events; narrow since, until, or categories for the rest."
        )
    return notes


def build_result(
    state: AppState,
    batch: EventBatch,
    *,
    company: CompanyRef,
    request: EventRequest,
    notes: list[str],
) -> CorporateEventsResult:
    """Build the tool result from a batch.

    Args:
        state (AppState): Server state.
        batch (EventBatch): Event reports read.
        company (CompanyRef): Identity of the company read.
        request (EventRequest): Tool arguments.
        notes (list[str]): Notes gathered earlier, such as window adjustments.

    Returns:
        CorporateEventsResult: Events newest first, coverage, paging, and notes.
    """
    titles = batch.titles()
    events = [
        event_model(record, titles=titles, detailed=request.detailed)
        for record in batch.records[: request.limit]
    ]
    coverage = EventCoverage(
        strategy=batch.strategy,
        kinds_queried=list(batch.queried),
        kinds_with_data=list(batch.with_data),
        kinds_failed=list(batch.failed) or None,
    )
    return CorporateEventsResult(
        company=company,
        as_of=state.today(),
        since=batch.window.start,
        until=batch.window.end,
        events=events,
        coverage=coverage,
        pagination=_pagination(batch, request),
        notes=[*notes, *_notes(batch, events, request)],
    )
