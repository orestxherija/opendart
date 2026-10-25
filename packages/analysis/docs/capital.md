# Capital structure

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.capital` reads a company's share capital from one periodic report: share counts by class, treasury
stock movements, share issuances and reductions, and the planned versus actual use of money raised. The workflow takes
the company, a `ResolvedPeriod` from [`resolve_period`](reports.md), the tables it needs as keyword-only callables (see
[data access](data-access.md)), and `today`.

Every table is a periodic-report service keyed by company, fiscal year, and report code, so one recipe binds them all
to the SDK. With the data-access recipe's `or_none` and `sdk_filing_search`:

```python
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from getpass import getpass
from typing import Any
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.capital import capital_structure
from opendart_analysis.reports import ReportQuery
from opendart_analysis.reports import resolve_period, today_kst
from opendart_analysis.upstream import Volatility


def sdk_periodic(method: Callable[..., Awaitable[Any]]):
    async def fetch(query: ReportQuery, /, *, volatility: Volatility) -> Sequence[Any] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(
            method(
                corporation_code=query.corp_code,
                fiscal_year=str(query.fiscal_year),
                report_period=query.report_code,
            )
        )
        return None if response is None else response.list

    return fetch


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    samsung = Company(corp_code="00126380", fye_month=12)
    today = today_kst()
    async with OpenDART(settings) as client:
        reports = client.periodic_reports
        resolved = await resolve_period(
            samsung,
            period="latest",
            fiscal_year=None,
            search_filings=sdk_filing_search(client),
            today=today,
        )
        structure = await capital_structure(
            samsung,
            resolved,
            sections=("shares", "treasury_stock"),
            fetch_share_counts=sdk_periodic(reports.stock_totqy_sttus),
            fetch_treasury_stock=sdk_periodic(reports.tesstk_acqs_dsps_sttus),
            today=today,
        )
        if structure is None:
            print("No share-count table for", [ref.label for ref in resolved.candidates[:3]])
            return
        counts = structure.shares
        print(structure.ref.label, counts.issued, counts.treasury, counts.outstanding)
        for movement in structure.treasury_stock or ():
            print(movement.share_class, movement.acquired, movement.retired, movement.end)


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `capital_structure(company, resolved, *, sections=SECTIONS, fetch_share_counts, fetch_treasury_stock=None, fetch_capital_changes=None, fetch_public_proceeds=None, fetch_private_proceeds=None, today, progress=None)` | `CapitalStructure` of the newest candidate report with share counts, or None. |
| `latest_share_counts(company, resolved, *, fetch_share_counts, today)` | `ShareCounts` of the newest candidate report that has them, or None. |
| `period_share_counts(company, ref, *, fetch_share_counts, today)` | `ShareCounts` of one period, in one call, or None. |
| `parse_share_counts(records, ref)` | The share-count table as `ShareCounts`; None when no row has a count. |
| `treasury_totals(records)`, `treasury_methods(records)` | Treasury movements by class (filed totals, else summed method rows), and by acquisition method. |
| `capital_changes(records)`, `change_category(kind)` | Issuances and reductions newest first; a filed type such as 유상증자(제3자배정) in English. |
| `proceeds_uses(public, private)` | Planned versus actual use of proceeds, public offerings first, in filed order. |
| `share_class(text)`, `is_note(text)` | `common`, `preferred`, or the class as filed; whether a row label marks the note row. |

`sections` holds any of `shares`, `treasury_stock`, `capital_changes`, and `use_of_proceeds` (`SECTIONS`, in reading
order). Share counts are read for every request, since they settle the period; a section's data access is needed only
when the section is requested, and a missing one raises `NotConfiguredError` before any call. A `CapitalStructure` has
the `ref` and `period_end`, the requested `sections`, `shares`, one field per section (None when not requested, empty
when the report has nothing to report), `sources` (the report as a `FilingSource`, titled when the filing index named
it for this period), and `notes`. The data rules are:

- **Share counts.** `ShareCounts` holds one `ShareClassCounts` per class in filed order, the all-classes `total` row
  when filed, the `note` row's text (such as `retired from profits: 자사주소각`), the report's `filing_number`, and the
  table's date (`as_of`). `issued`, `treasury`, and `outstanding` read the total row, or add up the classes; `primary`
  is the common-share row, else the first class. A blank class counts as common shares.
- **Treasury stock.** Per class, the opening and closing balance and the shares acquired, disposed of, and retired.
  Totals come from the filed total rows, else from the method rows added up; methods read broadest level first, such
  as `직접 취득 > 장내 직접 취득`.
- **Capital changes.** Dated changes come newest first, then undated ones in filed order; rows with neither a date nor
  a share count are dropped. Prices and par values are won per share.
- **Use of proceeds.** `amount_paid`, `plan`, and `actual_status` come from reports filed before 2018.
- **Amounts.** Integers as filed; dashes and blanks are None. Rows of dashes are dropped. Text stays as filed, often
  Korean.

The workflow probes at most three candidate periods for share counts, then reads each requested section once, all
concurrently; the first failure is raised unchanged after the other calls finish. Calls state `period_volatility`:
`high` until two weeks after a period's filing deadline, then `low`. `progress` receives one message once the period
is settled.

| Callable | Record Protocol | SDK method |
| --- | --- | --- |
| `FetchShareCounts` | `ShareCountRecord` | `periodic_reports.stock_totqy_sttus` |
| `FetchTreasuryStock` | `TreasuryRecord` | `periodic_reports.tesstk_acqs_dsps_sttus` |
| `FetchCapitalChanges` | `CapitalChangeRecord` | `periodic_reports.irds_sttus` |
| `FetchPublicProceeds` | `PublicProceedsRecord` | `periodic_reports.pssrp_cptal_use_dtls` |
| `FetchPrivateProceeds` | `PrivateProceedsRecord` | `periodic_reports.prvsrp_cptal_use_dtls` |

Each takes a `ReportQuery` (`corp_code`, `fiscal_year`, `report_code`); pass `str(query.fiscal_year)` and
`query.report_code` to the SDK and return `response.list` as it is.
