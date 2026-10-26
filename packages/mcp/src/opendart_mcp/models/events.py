"""Output models for corporate events from major-issue and registration reports."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from opendart_mcp.models.common import CompanyOutput, OutputModel, Pagination

type TermValue = str | int | float | bool | None

Strategy = Literal["requested", "filing_index", "all_kinds"]
"""How the event kinds to query were chosen."""


class EventDate(OutputModel):
    """A dated action in an event, such as a record date or a conversion window opening."""

    what: str = Field(description="Action code, such as record_date or conversion_start.")
    date: dt.date


class EventField(OutputModel):
    """One filled report field with its catalog label (detailed format)."""

    name: str
    label: str
    value: TermValue = None
    raw: str | None = Field(default=None, description="Value as filed, when it differs.")
    section: str | None = None


class CorporateEvent(OutputModel):
    """One event: the latest version of its filing, summarized."""

    kind: str
    group: str
    filed: dt.date | None = Field(default=None, description="Date of the latest version.")
    board_date: dt.date | None = None
    filing_number: str
    headline: str
    key_terms: dict[str, TermValue] = Field(
        default_factory=dict, description="Amounts in KRW; *_pct in percent; prices per share."
    )
    dates: list[EventDate] = Field(default_factory=list)
    flags: list[str] | None = Field(default=None, description="Red flags; omitted when none.")
    dart_url: str
    fields: list[EventField] | None = None


class EventCoverage(OutputModel):
    """Which event reports were read."""

    strategy: Strategy = Field(
        description="requested, filing_index (kinds the company filed), or all_kinds."
    )
    kinds_queried: list[str]
    kinds_with_data: list[str]
    kinds_failed: list[str] | None = None


class CorporateEventsResult(CompanyOutput):
    """Material events of one company, newest first."""

    since: dt.date = Field(description="First original filing date covered.")
    until: dt.date
    events: list[CorporateEvent]
    coverage: EventCoverage
    pagination: Pagination | None = None
