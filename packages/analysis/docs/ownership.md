# Ownership and control

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.ownership` maps who controls a company and who has been trading its shares. `ownership_report`
reads the control snapshot from one periodic report: the largest shareholder and related parties, the group's stake in
the voting class, minority shareholders, share counts, a free-float estimate, and changes of the largest shareholder.
`holding_reports` reads the 5% holder and insider ownership reports filed in a window. Both take the tables they need
as keyword-only callables (see [data access](data-access.md)) and `today`.

With the data-access recipe's `or_none` and `sdk_filing_search`, and `sdk_periodic` from the
[capital guide](capital.md), this reads the latest control snapshot and the last 180 days of holding reports:

```python
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from getpass import getpass
from typing import Any
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.ownership import HoldingQuery, holding_reports, ownership_report
from opendart_analysis.reports import resolve_period, today_kst
from opendart_analysis.upstream import Volatility


def sdk_holdings(method: Callable[..., Awaitable[Any]]):
    async def fetch(query: HoldingQuery, /, *, volatility: Volatility) -> Sequence[Any] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(method(corporation_code=query.corp_code))
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
        report = await ownership_report(
            samsung,
            resolved,
            fetch_largest_holders=sdk_periodic(reports.hyslr_sttus),
            fetch_share_counts=sdk_periodic(reports.stock_totqy_sttus),
            fetch_control_changes=sdk_periodic(reports.hyslr_chg_sttus),
            fetch_minority_holders=sdk_periodic(reports.mrhl_sttus),
            today=today,
        )
        if report is not None:
            snapshot = report.snapshot
            print(report.ref.label, snapshot.largest_shareholder, snapshot.controlling_pct)
            print("free float", snapshot.free_float_estimate_pct, "in", snapshot.share_class)
            for holder in snapshot.holders[:5]:
                print(holder.name, holder.relation, holder.share_class, holder.pct_end)
        activity = await holding_reports(
            samsung.corp_code,
            since=today - timedelta(days=180),
            fetch_major_holdings=sdk_holdings(client.equity_disclosures.majorstock),
            fetch_insider_holdings=sdk_holdings(client.equity_disclosures.elestock),
            today=today,
        )
        print(activity.insider_activity)
        for filed in activity.insider[:5]:
            print(filed.filed, filed.reporter, filed.position, filed.change)


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `ownership_report(company, resolved, *, fetch_largest_holders, fetch_share_counts, fetch_control_changes, fetch_minority_holders, today)` | `OwnershipReport` of the newest candidate report with a largest-shareholder table, or None. |
| `holding_reports(corp_code, *, since, fetch_major_holdings, fetch_insider_holdings, today)` | `HoldingReports` filed from `since` to `today`, newest first, with their counts. |
| `control_snapshot(records, counts, minority=None)` | `ControlSnapshot` of one largest-shareholder table. |
| `control_changes(records)`, `minority_holders(records)` | Changes of the largest shareholder, newest first; the first minority-shareholder row with figures. |
| `free_float(issued, controlling, treasury)`, `relation(text)` | The free-float estimate; a filed relation such as 최대주주의 특수관계인 in English (`RELATIONS`). |
| `activity(changes)`, `predates_listings(since, today)` | Counts by direction of change; whether a window starts before the listings reach (`LISTING_MONTHS`, 24). |

An `OwnershipReport` has the `ref` and `period_end`, the `snapshot`, `control_changes`, the report's `shares` (a
[`ShareCounts`](capital.md)), the period the minority figures come from (`minority_ref`), `sources`, and `notes`. The
data rules are:

- **Control.** Control is measured in the voting class: common shares when the group holds them, else the class it
  holds. The class's filed "Total" row gives the group's shares and percentages at the period start and end; without
  one, the class's holdings are added up. `holders` lists every holding without total rows: the voting class's largest
  first, then the other classes' largest first; `group_members` counts distinct holders in all classes. The largest
  shareholder is the holder filed as such (최대주주 본인), else the biggest holding of the class.
- **Free float.** `free_float_estimate_pct` is the class's issued shares minus the group's and treasury shares, over
  issued shares, in percent rounded to two decimals; treasury stock the group lists itself is not subtracted twice.
  Other large holders and lock-ups are not excluded, so it is an estimate. It is None without share counts or the
  group's total.
- **Minority shareholders.** Quarterly and half-year reports usually omit them, so the prior annual report is read
  too; a note says so, and the annual report joins `sources`.
- **Holding reports.** OpenDART lists about two years of 5% holder and insider reports per company, oldest first.
  Reports filed in the window are kept newest first by filing number, which starts with the filing date; changes are
  signed, and percentage changes such as `-0.00` read as `0.0`. Reports with a malformed filing number are skipped.
  `major_activity` and `insider_activity` count every report kept.
- **Units.** Percentages are floats in percent of the holding class's issued shares, as filed; share counts are
  integers. Names, positions, and causes stay as filed, often Korean; common relations and statuses are translated.
- **Provenance.** `sources` lists the periodic report, titled when the filing index named it for this period; holding
  reports carry their own filing numbers.

`ownership_report` probes at most three candidate periods for named largest-shareholder rows, then reads the period's
share counts, control changes, and minority shareholders concurrently, plus one call for the prior annual report's
minority figures when needed. `holding_reports` makes two calls, concurrently. The first failure is raised unchanged
after the other calls finish. Periodic tables state `period_volatility`; holding reports are `medium`, since they
accumulate during the day. `holding_reports` raises `ValueError` when `since` is after `today`.

| Callable | Query | Record Protocol | SDK method |
| --- | --- | --- | --- |
| `FetchLargestHolders` | `ReportQuery` | `LargestHolderRecord` | `periodic_reports.hyslr_sttus` |
| `FetchShareCounts` | `ReportQuery` | `ShareCountRecord` | `periodic_reports.stock_totqy_sttus` |
| `FetchControlChanges` | `ReportQuery` | `ControlChangeRecord` | `periodic_reports.hyslr_chg_sttus` |
| `FetchMinorityHolders` | `ReportQuery` | `MinorityRecord` | `periodic_reports.mrhl_sttus` |
| `FetchMajorHoldings` | `HoldingQuery` (`corp_code`) | `MajorHoldingRecord` | `equity_disclosures.majorstock` |
| `FetchInsiderHoldings` | `HoldingQuery` | `InsiderHoldingRecord` | `equity_disclosures.elestock` |
