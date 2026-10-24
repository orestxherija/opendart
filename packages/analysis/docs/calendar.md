# Corporate-action calendar

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.calendar` collects forward corporate-action dates for one company or a watchlist: subscription and
payment dates, record dates, listings, conversion, warrant, and exchange windows, buyback periods, shareholder
meetings, appraisal-rights windows, trading suspensions, effective dates, and bond maturities. Event dates come from
[corporate events](events.md) and debt maturities from [debt securities](debt.md). `corporate_action_calendar` takes
the [filing discovery](filings.md) `ReadFilingPage` and the `FetchService` from the [extracts guide](extracts.md);
`read_debt_maturities` adds `SearchFilings` from the [data-access recipe](data-access.md) to resolve each company's
latest periodic report. With `or_none`, `sdk_filing_search`, `sdk_filing_pages`, and `sdk_fetch_service` from those
guides, the next 90 days for two companies:

```python
import asyncio
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.calendar import (
    CalendarSubject,
    calendar_kinds,
    calendar_window,
    corporate_action_calendar,
    read_debt_maturities,
)
from opendart_analysis.reports import today_kst


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    companies = [
        CalendarSubject("00126380", "SAMSUNG ELECTRONICS CO,.LTD", korean_name="삼성전자"),
        CalendarSubject("00164779", "SK hynix Inc.", korean_name="에스케이하이닉스"),
    ]
    today = today_kst()
    window = calendar_window("90d", include_past=None, today=today)
    selection = calendar_kinds(None)  # Every kind with dates, and debt maturities.
    async with OpenDART(settings) as client:
        fetch = sdk_fetch_service(client)
        maturities = read_debt_maturities(
            search_filings=sdk_filing_search(client), fetch_service=fetch, today=today
        )
        calendar = await corporate_action_calendar(
            companies,
            window=window,
            kinds=selection.events,
            maturities=maturities if selection.debt else None,
            fetch_service=fetch,
            read_filing_page=sdk_filing_pages(client),
            today=today,
        )
    names = {company.corp_code: company.name for company in companies}
    for item in calendar.items:
        print(item.date, names[item.corp_code], item.action, item.filing_number, dict(item.details))
    for company in calendar.companies:
        debt = company.maturities
        if debt is not None and debt.bonds is not None:
            print(company.subject.name, debt.bonds.due_within_1y, debt.bonds.outstanding)
        if company.failed or company.error:
            print(company.subject.name, company.failed, company.error)


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `calendar_window(horizon="90d", include_past=None, *, today)` | The calendar's dates: today, or `include_past` (an ISO date or `30d`), to `horizon` (an ISO date or `90d`, `6m`, `1y`). |
| `calendar_kinds(names)`, `KindSelection`, `DEBT_KIND` | Event groups or kinds, plus `debt_maturity`, to read; kinds without calendar dates are listed in `dropped`. |
| `corporate_action_calendar(subjects, *, window, kinds=None, maturities=None, fetch_service, read_filing_page, policy=DEFAULT_POLICY, max_companies=20, today, progress=no_progress)` | A `CorporateActionCalendar`: `window`, `reads`, per-company `companies`, and sorted `items`. |
| `CalendarSubject` | `corp_code`, `name`, `korean_name`, and `fye_month` of a company to cover. |
| `CalendarItem` | `date`, `corp_code`, `action`, `source_kind`, `filing_number`, and `details`. |
| `CompanyCalendar` | `subject`, `items`, event `batches` read (`events`), `failed` kinds, the maturity reader's answer (`maturities`), and a tolerated `error`. |
| `read_debt_maturities(*, search_filings, fetch_service, today)`, `debt_maturities`, `DebtMaturities`, `BondsDue` | Debt maturities in the window from the latest periodic reports, and the corporate bonds due within a year. |
| `Reads`, `LOOKBACK_MONTHS`, `LONG_LOOKBACK_MONTHS`, `LONG_KINDS` | The filing windows read before the first date. |
| `event_items`, `merge_maturities`, `sort_key`, `REGISTERED`, `ACTION_ORDER` | Items from event records already read, merged and ordered the same way. |

How the calendar is built:

- **Window.** `include_past` must not be after today and `horizon` not before it; otherwise `CalendarWindowError`
  names the argument (`include_past` is checked first). Unknown kinds raise `UnknownKindsError`, and kinds that all
  lack calendar dates, without debt, raise `UndatedKindsError`. Every request error is a `CalendarRequestError`.
- **Lookback.** Schedules are filed weeks to a year ahead, so event reports are read from filings made in the
  `LOOKBACK_MONTHS` (12) before the first calendar date, and convertible, warrant, exchangeable, contingent capital,
  and debt offering reports (`LONG_KINDS`) from the `LONG_LOOKBACK_MONTHS` (36) before it: conversion often opens more
  than a year after the filing, and bonds mature years later. Windows end today and never start before 2015.
  OpenDART applies them to the original filing date and folds amendments into the original row, so dates are the
  latest amended ones.
- **Kinds.** With `kinds`, exactly those are read, bonds over the long window and the rest over the short one; an
  empty tuple reads no event reports. Without them, one search of the company's filing index over the long window
  picks the kinds for both: a kind outside `LONG_KINDS` is read only when it was filed within the short window, and
  every kind of an index group with more than `policy.max_index_pages` pages counts as filed.
- **Items.** Only schedule dates within the window become items; facts such as a lawsuit's filing date do not. Each
  item's `details` hold the event's label (`event`) and its first three key terms (`DETAIL_TERMS`) that are not
  flags.
- **Deduplication.** A registration statement's item with the same action and date as its decision's is dropped, and
  the decision cites it in `details["registration_filing"]`. The statement names its decision in `rpt_rcpn`; when an
  amendment changed the decision's filing number, decisions of the kinds the statement registers (`REGISTERED`) on
  that date match instead, and an ambiguous statement cites neither. A debt offering's exercise window matches a
  conversion or exchange window. A debt maturity with the same date and face value as an event maturity replaces it
  and cites it in `details["offering_filing"]`. Repeated corporation codes are read once.
- **Debt maturities.** `maturities` is any coroutine function of a subject and the window that returns an object with
  `items`; items outside the window are dropped, and the answer is kept in `CompanyCalendar.maturities`.
  `read_debt_maturities` resolves the latest period with `resolve_period`, reads `maturity_schedule` (see
  [debt securities](debt.md)), and returns `DebtMaturities`: `debt_maturity` items with the instrument, original face
  value in won, coupon, redemption status, and other issuer, each citing the periodic report that lists it; the
  `period` read (None when no report had debt tables); and `bonds`, the latest corporate-bond ladder's total and the
  part due within a year of its period end (the fiscal year-end month dates a period without a known end). Issuance
  records list only recent issues, so the ladder is the complete view.
- **Order.** Items sort by date, company name, action (`ACTION_ORDER`, debt maturities last), and filing number.
  Every item cites its filing; nothing is capped, so callers bound the output themselves.
- **Partial results.** Companies are read concurrently, each company's events and debt at the same time. An event
  service failure that `policy.tolerate` accepts lands in `failed`; a failure of the filing index or the maturity
  reader that it accepts leaves that company without items, with the exception in `error`. Any other exception
  propagates unchanged after every company has finished. `progress` receives "1/2 SK hynix Inc." as each company
  finishes, and more than `max_companies` distinct companies raise `TooManyCompaniesError` before any call.

Event services use `medium` volatility and the filing index `high`, as in [corporate events](events.md); the debt
reader's calls follow [debt securities](debt.md). Analysis never retries or caches.
