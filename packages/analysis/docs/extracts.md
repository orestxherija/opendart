# Periodic-report extracts

Part of the [opendart-analysis guide](../README.md).

Thirty OpenDART services return tables from periodic reports, such as dividends, shareholders, executives, and debt
securities, keyed by corporation code, fiscal year, and report code. `opendart_analysis.extracts` fetches one service
for one company and period through a caller-supplied `FetchService`, runs several fetches at once, reads the records'
all-string fields safely, and lists the filings the records came from. With the [data-access recipe](data-access.md),
this callable binds catalog service names to the SDK client's methods:

```python
from opendart import OpenDART
from opendart_analysis.catalog import service
from opendart_analysis.upstream import FetchService, Volatility


def sdk_fetch_service(client: OpenDART) -> FetchService:
    async def fetch_service(
        name: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        del volatility  # This recipe caches nothing.
        spec = service(name)
        method = getattr(getattr(client, spec.resource), spec.name)
        return await or_none(method(**params))

    return fetch_service
```

The latest annual dividend table, probed under each fiscal-year label of the filed report, with its provenance:

```python
import asyncio
from dataclasses import dataclass
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.extracts import (
    checked,
    fetch_records,
    filed_text,
    probe_attempts,
    sources,
    text,
)
from opendart_analysis.reports import first_available, resolve_period, today_kst


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    samsung = Company(corp_code="00126380", fye_month=12)
    today = today_kst()
    async with OpenDART(settings) as client:
        resolved = await resolve_period(
            samsung,
            period="FY",
            fiscal_year=None,
            search_filings=sdk_filing_search(client),
            today=today,
        )
        fetch = sdk_fetch_service(client)
        found = await first_available(
            resolved,
            lambda ref: fetch_records(
                "alot_matter", company=samsung, ref=ref, fetch_service=fetch, today=today
            ),
            attempts=probe_attempts(resolved),
        )
        if found is None:
            print("No dividend table in", checked(resolved))
            return
        ref, rows = found
        for row in rows:
            label, kind = filed_text(text(row, "se")), filed_text(text(row, "stock_knd"))
            print(ref.label, label, kind, text(row, "thstrm"))
        numbers = (text(row, "filing_number") for row in rows)
        print([source.filing_number for source in sources(numbers, resolved.report)])


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `fetch_response(service, *, company, ref, fetch_service, today)` | One service's response for a company and `PeriodRef`, or None for no data. |
| `fetch_records(service, *, company, ref, fetch_service, today)` | The response's `list` records, or None for no data. |
| `gather_all(calls)` | Await calls concurrently; results in call order, or the first failure unwrapped. |
| `probe_attempts(resolved)` | How many candidates to probe: one per fiscal-year label of a filed report, else `PROBE_ATTEMPTS`. |
| `checked(resolved)` | The report title in quotes, or the probed period labels, for notes about missing data. |
| `sources(numbers, report=None)` | Distinct valid filing numbers as `FilingSource` (`filing_number`, `title`), titled by the report. |
| `records(response, name="list")`, `text(record, name)` | A record container (`group` for the Ver 2.0 services) and a string field, safely. |
| `amount(record, name)` | A whole-number field such as `1,234,567` or `(1,234)`; None for `-`, blanks, and fractions. |
| `filed_text(value)`, `fold(value)`, `is_total(value)` | Clean text without "not applicable" placeholders; a label folded for matching; total rows. |
| `term_ages(labels)` | Each row's term age (0 current, 1 prior, ...) from labels such as `제57기 (당기)` or `2025`. |
| `PERIODIC_PARAMS` | `corporation_code`, `fiscal_year`, and `report_period`, the parameters every such service takes. |

`company` is any object with `corp_code` and `fye_month` (`opendart_analysis.reports.FiscalCompany`). Service, field,
and container names are the SDK's, as `opendart_analysis.catalog` lists them. Each fetch states `high` volatility until
two weeks after the period's filing deadline and `low` afterwards (`period_volatility`), so a caching source picks up a
report filed or corrected meanwhile.

`gather_all` lets every call finish, so a caching source keeps each answer, then raises the first failure in call
order as it is, never inside an exception group, whether it is an `AnalysisError` or an exception from the caller's
data access. Fetches raise no analysis errors of their own: failures of `fetch_service` reach the caller unchanged.

`term_ages` lets years decide when every label has one, then term numbers (filers sometimes mislabel older terms as
당기, current), then the words 당기, 전기, and 전전기 (current, prior, two years prior), and finally the order in which
labels first appear. Blank labels continue the previous row's term.
