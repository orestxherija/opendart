"""Output models for the corporate-action calendar (also the calendar app's data contract)."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from opendart_mcp.models.common import CompanyRef, OutputModel, ToolOutput

type DetailValue = str | int | float | None


class CalendarItem(OutputModel):
    """One dated corporate action."""

    date: dt.date
    company: CompanyRef
    action: str = Field(description="Action code, such as record_date or conversion_start.")
    source_kind: str = Field(description="Event kind the date comes from.")
    filing_number: str
    dart_url: str
    details: dict[str, DetailValue] = Field(default_factory=dict)


class CalendarResult(ToolOutput):
    """Corporate-action dates for one company or a watchlist, sorted by date."""

    start: dt.date = Field(description="First date included.")
    end: dt.date = Field(description="Last date included (the horizon).")
    horizon_days: int = Field(description="Days from today to the horizon.")
    companies: list[CompanyRef]
    items: list[CalendarItem]
