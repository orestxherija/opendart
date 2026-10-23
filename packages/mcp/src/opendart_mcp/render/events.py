"""Markdown view of corporate events: one table row per event, labeled fields when detailed."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.events import ACTIONS
from opendart_mcp.render.markdown import company_line, footer, join, section, table

if TYPE_CHECKING:
    from opendart_mcp.models.common import Pagination
    from opendart_mcp.models.events import CorporateEvent, CorporateEventsResult, EventCoverage

DATES_SHOWN: Final = 4


def plural(count: int, noun: str, many: str | None = None) -> str:
    """Count a noun.

    Args:
        count (int): How many.
        noun (str): Singular noun.
        many (str | None): Plural noun; defaults to the singular with an "s".

    Returns:
        str: For example "1 event" or "3 events".
    """
    return f"{count} {noun if count == 1 else many or noun + "s"}"


def action_label(code: str) -> str:
    """Return the English label of an action code.

    Args:
        code (str): Action code, such as record_date.

    Returns:
        str: Label, or the code with spaces for unknown codes.
    """
    action = ACTIONS.get(code)
    return action.label if action else code.replace("_", " ")


def _dates(event: CorporateEvent) -> str:
    """List an event's first dated actions.

    Args:
        event (CorporateEvent): Event.

    Returns:
        str: For example "Subscription 2026-11-12; Conversion period opens 2027-11-12".
    """
    shown = [f"{action_label(d.what)} {d.date.isoformat()}" for d in event.dates[:DATES_SHOWN]]
    more = len(event.dates) - DATES_SHOWN
    return "; ".join(shown) + (f"; +{more} more" if more > 0 else "")


def _fields(event: CorporateEvent) -> str:
    """Render the labeled fields of a detailed event.

    Args:
        event (CorporateEvent): Event with fields.

    Returns:
        str: Titled table, or an empty string without fields.
    """
    fields = event.fields or []
    values = [(f.label, f.raw if f.raw is not None else f.value) for f in fields]
    if any(field.section for field in fields):
        rows = [(field.section, *value) for field, value in zip(fields, values, strict=True)]
        body = table(("Section", "Field", "Value"), rows)
    else:
        body = table(("Field", "Value"), values)
    return section(f"{event.filing_number}: {event.kind}", body)


def _coverage(coverage: EventCoverage) -> str:
    """Describe which reports were read.

    Args:
        coverage (EventCoverage): Coverage of the result.

    Returns:
        str: One or two sentences.
    """
    found = ", ".join(coverage.kinds_with_data) or "none"
    read = plural(len(coverage.kinds_queried), "event report")
    text = f"Read {read} ({coverage.strategy}); data for: {found}."
    if coverage.kinds_failed:
        text += f" No answer for: {", ".join(coverage.kinds_failed)}."
    return text


def _next(pagination: Pagination | None) -> str:
    """Show the call that returns more events.

    Args:
        pagination (Pagination | None): Paging of the result.

    Returns:
        str: The next call, or an empty string.
    """
    if pagination is None or pagination.next_call is None:
        return ""
    call = pagination.next_call
    arguments = ", ".join(f"{name}={value!r}" for name, value in call.arguments.items())
    return f"More: {call.tool}({arguments})"


def render_events(result: CorporateEventsResult) -> str:
    """Render corporate events.

    Args:
        result (CorporateEventsResult): Events result.

    Returns:
        str: Markdown.
    """
    rows = [
        (
            event.filed,
            event.kind,
            event.headline,
            _dates(event),
            ", ".join(event.flags or ()),
            event.filing_number,
        )
        for event in result.events
    ]
    headers = ("Filed", "Kind", "Headline", "Dates", "Flags", "Filing")
    window = f"Original filings from {result.since} to {result.until}; {plural(len(result.events), "event")}, newest first."
    return join(
        f"**Corporate events: {company_line(result.company)}**",
        window,
        table(headers, rows),
        *(_fields(event) for event in result.events),
        _coverage(result.coverage),
        _next(result.pagination),
        footer(result),
    )
