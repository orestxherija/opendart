"""Corporate-action calendar: forward dates from event reports and debt maturities.

``corporate_action_calendar`` reads each company's major-issue and registration reports over
lookback windows before the first calendar date (a year, three years for bond reports), turns
their schedule dates into items, merges dates that a registration statement repeats from its
decision, and adds debt maturities from a caller-supplied reader, such as
``read_debt_maturities`` over the latest periodic reports. One ``CallLimit`` shared by the
calendar and the reader bounds every upstream call in flight:

    window = calendar_window("90d", today=today)
    selection = calendar_kinds(None)
    limit = CallLimit(MAX_CONCURRENCY)
    calendar = await corporate_action_calendar(
        [CalendarSubject("00126380", "Samsung Electronics", korean_name="삼성전자")],
        window=window,
        kinds=selection.events,
        maturities=read_debt_maturities(
            search_filings=search, fetch_service=fetch, today=today, limit=limit
        ),
        fetch_service=fetch,
        read_filing_page=read_page,
        limit=limit,
        today=today,
    )

Modules: ``request`` (window, kinds, and companies), ``lookback`` (which filings are read),
``items`` (items, merging, and order), ``reads`` (one company's event reports),
``maturities`` (debt maturities), and ``assemble``. Data access follows
``opendart_analysis.upstream``. Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.calendar.assemble import (
    CompanyCalendar,
    CorporateActionCalendar,
    MaturityAnswer,
    ReadMaturities,
    corporate_action_calendar,
)
from opendart_analysis.calendar.items import (
    ACTION_ORDER,
    DEBT_ACTION,
    DEBT_SOURCE_KIND,
    DETAIL_TERMS,
    REGISTERED,
    CalendarItem,
    Detail,
    event_items,
    merge_maturities,
    sort_key,
)
from opendart_analysis.calendar.lookback import (
    LONG_KINDS,
    LONG_LOOKBACK_MONTHS,
    LOOKBACK_MONTHS,
    RECENT_KINDS,
    Reads,
    lookback,
)
from opendart_analysis.calendar.maturities import (
    BondsDue,
    DebtMaturities,
    bonds_due,
    debt_maturities,
    maturity_item,
    read_debt_maturities,
    schedule_maturities,
)
from opendart_analysis.calendar.reads import filed_since, indexed_kinds, read_events
from opendart_analysis.calendar.request import (
    DEBT_KIND,
    DEFAULT_HORIZON,
    MAX_COMPANIES,
    MAX_CONCURRENCY,
    CalendarRequestError,
    CalendarSubject,
    CalendarWindowError,
    KindSelection,
    TooManyCompaniesError,
    UndatedKindsError,
    UnknownKindsError,
    calendar_kinds,
    calendar_window,
)
from opendart_analysis.domain.dates import DateWindow

__all__ = [
    "ACTION_ORDER",
    "DEBT_ACTION",
    "DEBT_KIND",
    "DEBT_SOURCE_KIND",
    "DEFAULT_HORIZON",
    "DETAIL_TERMS",
    "LONG_KINDS",
    "LONG_LOOKBACK_MONTHS",
    "LOOKBACK_MONTHS",
    "MAX_COMPANIES",
    "MAX_CONCURRENCY",
    "RECENT_KINDS",
    "REGISTERED",
    "BondsDue",
    "CalendarItem",
    "CalendarRequestError",
    "CalendarSubject",
    "CalendarWindowError",
    "CompanyCalendar",
    "CorporateActionCalendar",
    "DateWindow",
    "DebtMaturities",
    "Detail",
    "KindSelection",
    "MaturityAnswer",
    "ReadMaturities",
    "Reads",
    "TooManyCompaniesError",
    "UndatedKindsError",
    "UnknownKindsError",
    "bonds_due",
    "calendar_kinds",
    "calendar_window",
    "corporate_action_calendar",
    "debt_maturities",
    "event_items",
    "filed_since",
    "indexed_kinds",
    "lookback",
    "maturity_item",
    "merge_maturities",
    "read_debt_maturities",
    "read_events",
    "schedule_maturities",
    "sort_key",
]
