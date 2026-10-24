# Dividends

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.dividends` reads a company's dividend history from the dividend table of its annual reports
(`alot_matter`): cash and stock dividends per share and in total, the payout ratio, yields, and the net income, EPS,
and par value they rest on, by share class and fiscal year. With `sdk_filing_search` from the
[data-access recipe](data-access.md) and `sdk_fetch_service` from the [extracts guide](extracts.md), this prints five
years of cash dividends per share:

```python
import asyncio
from dataclasses import dataclass
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.dividends import dividend_history
from opendart_analysis.extracts import checked
from opendart_analysis.reports import resolve_period, today_kst


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
        history = await dividend_history(
            samsung,
            resolved,
            years=5,
            fetch_service=sdk_fetch_service(client),
            today=today,
        )
    if history is None:
        print("No dividend table in", checked(resolved))
        return
    for row in history.rows:
        if row.measure == "cash_dps":
            print(row.share_class, row.unit, row.values)
    print([source.filing_number for source in history.sources], history.notes)


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `dividend_history(company, resolved, *, years=3, fetch_service, today)` | A `DividendHistory`, or None when no candidate period has a dividend table. |
| `DividendHistory` | `ref` (newest annual period with data), `rows`, `fiscal_years` (newest first), `sources`, `missing`, `notes`. |
| `DividendRow` | `measure`, `share_class`, `basis`, `unit`, `label` as filed, and `values` by fiscal year, newest first. |
| `merge(batches, years)` | Rows of several annual reports' records, newest report first, merged for the given fiscal years. |
| `measure(label)`, `unit(label, kind)`, `basis(label)`, `share_class(value)`, `value(raw, kind, scale)` | Classify one row and convert one filed value. |
| `MEASURES`, `MAX_YEARS`, `YEARS_PER_REPORT`, `SERVICE`, `YIELD_NOTE` | Measure order, 10, 3, `alot_matter`, and the yield note. |

Resolve the period with `period="FY"`; `dividend_history` raises `ValueError` for any other candidate, or for `years`
outside 1 to `MAX_YEARS`. The rules are:

- **Measures.** Rows are classified by keywords in their English or Korean labels into `cash_dps`, `stock_dps`,
  `cash_dividends`, `stock_dividends`, `payout_ratio`, `cash_yield`, `stock_yield`, `net_income`, `eps`, `par_value`,
  or `other` for anything unrecognized. Rows are listed in that order, then in filing order.
- **Units.** Values are converted from the unit a label states, or the table's standard unit, to `KRW`, `KRW/share`,
  `%`, or `shares/share`: totals and net income filed in KRW million become won. Percentages are floats, whole
  numbers ints, and `-` is missing. Yields are as filed: OpenDART has no market prices, so they are not recomputed.
- **Share classes and basis.** 보통주 and 우선주 become `common` and `preferred`, other classes stay as filed, and
  company totals have none. Earnings rows carry `consolidated` or `separate` when their label says so.
- **Fiscal years.** Each annual report holds three fiscal years (current, prior, two years prior). Longer histories
  fetch every third earlier annual report concurrently, back to fiscal 2015, and the newest report wins a year that
  two reports share. `missing` lists earlier reports without a table, and `notes` says so.
- **Rows kept.** `rows` holds every merged row, including par value and rows without values, so a caller chooses
  what to show; `fiscal_years` lists the years with any value.

The acquisition is bounded: the candidate periods of a filed report's fiscal-year labels, or at most three periods
by filing deadline, then `ceil(years / 3) - 1` earlier reports. Each call states the period's volatility, `high`
until two weeks after its filing deadline and `low` afterwards. Failures of `fetch_service` reach the caller
unchanged, after concurrent calls finish.
