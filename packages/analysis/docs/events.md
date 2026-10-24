# Corporate events

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.events` reads a company's material events, such as capital raises, convertible bonds, buybacks,
mergers, and lawsuits, from OpenDART's 42 major-issue and registration-statement services, and interprets each report:
a one-line headline, normalized key terms, dated schedule actions, and flags. `fetch_events` takes two callables that
follow the [data-access convention](data-access.md): a `FetchService` for the event services, keyed by the catalog's
SDK method names, and the `ReadFilingPage` from [filing discovery](filings.md) for the company's filing index. This
recipe binds the first to a caller-owned SDK client, with `or_none` from the data-access recipe and `sdk_filing_pages`
from the filing-discovery guide:

```python
import asyncio
from datetime import date
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.catalog import service
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.events import (
    EventQuery,
    amendment_flag,
    covered_window,
    describe,
    fetch_events,
)
from opendart_analysis.upstream import FetchService, Volatility


def sdk_service_fetch(client: OpenDART) -> FetchService:
    async def fetch_service(
        name: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        del volatility  # This recipe caches nothing.
        method = getattr(getattr(client, service(name).resource), name)
        return await or_none(method(**params))

    return fetch_service


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    window = covered_window(
        DateWindow(date(2025, 10, 22), date(2026, 10, 22)), today=date(2026, 10, 22)
    )
    async with OpenDART(settings) as client:
        batch = await fetch_events(
            EventQuery("00126380", window, name="Samsung Electronics"),
            fetch_service=sdk_service_fetch(client),
            read_filing_page=sdk_filing_pages(client),
        )
    titles = batch.titles()
    for record in batch.records:
        view = describe(record)
        flags = [*view.flags, *filter(None, [amendment_flag(view, titles)])]
        print(
            view.filing_number, view.label, view.headline, dict(view.key_terms), view.dates, flags
        )
    print(batch.strategy, batch.queried, batch.failed)


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `fetch_events(query, *, fetch_service, read_filing_page, policy=DEFAULT_POLICY, progress=no_progress)` | An `EventBatch` of the company's event records, newest filing first. |
| `EventQuery` | `corp_code`, `window`, `kinds` (None lets the filing index choose), `restrict`, and `name` for progress messages. |
| `ReadPolicy` | `tolerate` (failures that mark a kind failed), `concurrency` (None leaves it to the source), and `max_index_pages` (3). |
| `EventBatch` | `corp_code`, `window`, `strategy`, `queried`, `failed`, `records`, `index`, `with_data`, and `titles()`. |
| `covered_window(window, *, today)`, `EARLIEST` | Clip a window to 2015-01-01 through today, or None when it misses that range. |
| `search_index`, `EventIndex`, `IndexedFiling` | The company's major-issue and offering filings, the kinds they name, and `unstructured()` filings no service covers. |
| `records_from(kind, response)`, `EventRecord`, `Row` | Group one service response into records; `raw()` and `value()` read a field. |
| `describe(record)`, `EventView` | Kind, group, label, headline, key terms, dated actions, flags, and board date. |
| `labeled_fields(record)`, `LabeledValue` | Every filled field with its catalog label, normalized value, raw text, and section. |
| `amendment_flag(view, titles)`, `AMENDED`, `POSSIBLY_AMENDED` | Whether the record reflects a corrected filing. |
| `event_flags`, `FLAG_FIELDS`, `event_dates`, `board_date`, `ACTIONS`, `CALENDAR_KINDS` | Flags, schedule dates and their 69 action codes, and the 36 kinds with forward-looking dates. |
| `kind_for_title`, `plain_title`, `normalize`, `parse_flag`, `parse_span`, `PRESENTATIONS` | Title-to-kind rules, value normalization, and the per-kind headline templates. |

How events are read:

- **Choosing services.** With `kinds`, exactly those services are read (`opendart_analysis.catalog.expand` turns group
  names such as `debt` into kinds). Without them, the company's major-issue (B) and offering (C) filings in the window
  are searched first, up to `max_index_pages` pages of 100 per group, and only the kinds whose titles appear are read:
  strategy `filing_index`. When a group has more pages, every kind of that group is read as well: strategy
  `all_kinds`. `restrict` limits the kinds the index may choose.
- **Calls.** Every service is called with `corporation_code`, `filing_start_date`, and `filing_end_date` (`YYYYMMDD`)
  and `medium` volatility, concurrently, at most `concurrency` at a time; index pages use `high` volatility.
  `progress` receives "Searching ...'s major-issue and offering filings" before the index and "3/12 event reports
  read (merger)" after each service.
- **Partial results.** A service whose call raises an exception that `policy.tolerate` accepts is listed in `failed`
  and the others are kept; by default only `DataSourceError` is tolerated. Any other exception, such as an exhausted
  quota, propagates unchanged: the first one in the order of the kinds read, after every call has finished. Analysis
  never retries.
- **Records.** Rows are grouped by filing number; rows without a valid one are skipped. Registration statements return
  sections, which are matched to the catalog's by title or, when titles differ, by their fields. A debt registration
  that offers several tranches becomes one record per tranche, so one filing number can appear more than once.
  `records_from` reads SDK response models and decoded JSON bodies alike.
- **Amendments.** OpenDART folds an amendment into the original decision's row: the latest filing number, the amended
  terms, and a window applied to the original filing date. `amendment_flag` returns `amended` when the index title of
  the latest filing has an amendment marker. Without an index title, a major-issue decision whose latest filing came
  more than `AMENDMENT_GAP_DAYS` (7) days after its board date returns `possibly_amended`.
- **Values.** By the catalog's field kind, amounts and counts become integers (won and shares), percentages floats,
  dates and periods ISO dates or `start/end` ranges, yes/no fields booleans, and dashes or blanks None; codes, ratios,
  and free text stay cleaned text. Headlines and key terms come from one handwritten presentation per kind.
