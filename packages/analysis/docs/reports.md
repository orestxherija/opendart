# Periodic reports

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.reports` turns a requested period (`latest`, `FY`, `Q1`, `H1`, or `Q3`, optionally with a fiscal
year) into candidate periods, best first, and probes them until one has data. With the [data-access recipe](data-access.md):

```python
import asyncio
from dataclasses import dataclass
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.reports import first_available, resolve_period, today_kst


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    samsung = Company(corp_code="00126380", fye_month=12)
    async with OpenDART(settings) as client:
        resolved = await resolve_period(
            samsung,
            period="latest",
            fiscal_year=None,
            search_filings=sdk_filing_search(client),
            today=today_kst(),
        )
        print(resolved.report.title if resolved.report else resolved.note)

        found = await first_available(
            resolved,
            lambda ref: or_none(
                client.financial_statements.fnltt_singl_acnt(
                    corporation_code=samsung.corp_code,
                    fiscal_year=str(ref.fiscal_year),
                    report_period=ref.report_code,
                )
            ),
        )
        if found is not None:
            ref, accounts = found
            print(ref.label, len(accounts.list or []))


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `resolve_period(company, *, period, fiscal_year, search_filings, today)` | A `ResolvedPeriod` with `candidates`, the defining `report`, and a `note`. |
| `latest_periodic_report(company, period="latest", *, search_filings, today)` | The newest final `PeriodicReport` from the last 15 months, or None. |
| `first_available(resolved, fetch, *, attempts=PROBE_ATTEMPTS)` | The first candidate (of at most 3) whose `fetch` returns data, with that data. |
| `period_volatility(ref, *, fye_month, today)` | `high` until two weeks after the period's filing deadline, then `low`. |
| `FiscalCompany` | Protocol for the company: `corp_code` and `fye_month` (fiscal year-end month). |
| `PeriodicReport` | `ref` (`PeriodRef`), parsed title (`PeriodicTitle`), `filing_number`, cleaned `title`, and `filed` date. |
| `PeriodRef`, `Period`, `ConcretePeriod`, `today_kst` | Fiscal year and period with `report_code` and `label`; period literals; today in Korea. |

Without a fiscal year, `resolve_period` searches one page (100 filings) of the company's final periodic reports filed
in the last 15 months, with `high` volatility. The report for the newest period wins, so an amended older report filed
later does not; among filings for one period, the latest is the final version. Its period comes first, under both
fiscal-year labels when the year ends in a month other than December, followed by deadline-based candidates that end
no later than it. When no report is found, or a fiscal year is given, candidates come from statutory filing deadlines
only, newest first, and the filing search is not called for a fiscal year; without a fiscal year, `note` says so.

`resolve_period` raises `PeriodUnavailableError`, a `MissingDataError` with `period`, `fiscal_year`, and
`first_fiscal_year` (2015), when no candidate exists because the period has not ended yet or predates OpenDART's
periodic data.
