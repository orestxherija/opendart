# Financial statements

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.financials` reads a company's financial statements over periods, its published indicators, its
equity investments, and its preliminary earnings, and compares several companies for one period. Each workflow takes
the company, the upstream operations it needs as keyword-only callables (see [data access](data-access.md)), and
`today`. Statement, indicator, and holdings workflows also take a `ResolvedPeriod` from
[`resolve_period`](reports.md), so the requested period is settled once and probed in order.

With the data-access recipe's `or_none` and `sdk_filing_search`, this binds the major accounts (the summary statements)
to an SDK client and reads the latest two half-year reports:

```python
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.financials import (
    FetchMajorAccounts,
    HistoryRequest,
    MajorAccountRecord,
    ReportQuery,
    major_accounts,
)
from opendart_analysis.reports import resolve_period, today_kst
from opendart_analysis.upstream import Volatility


def sdk_major_accounts(client: OpenDART) -> FetchMajorAccounts:
    async def fetch_major_accounts(
        query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[MajorAccountRecord] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(
            client.financial_statements.fnltt_singl_acnt(
                corporation_code=query.corp_code,
                fiscal_year=str(query.fiscal_year),
                report_period=query.report_code,
            )
        )
        return None if response is None else response.list

    return fetch_major_accounts


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    samsung = Company(corp_code="00126380", fye_month=12)
    async with OpenDART(settings) as client:
        today = today_kst()
        resolved = await resolve_period(
            samsung,
            period="latest",
            fiscal_year=None,
            search_filings=sdk_filing_search(client),
            today=today,
        )
        history = await major_accounts(
            samsung,
            resolved,
            request=HistoryRequest(years=2),
            fetch_major_accounts=sdk_major_accounts(client),
            today=today,
        )
        if history is None:
            print("No data for", [ref.label for ref in resolved.candidates])
            return
        for line in sorted(history.report.lines, key=lambda line: line.rank)[:5]:
            print(line.account, line.values.get(history.ref), line.cumulative.get(history.ref))
        print(history.ref.label, history.derived)


asyncio.run(main())
```

| Workflow | Result |
| --- | --- |
| `major_accounts(company, resolved, *, request, fetch_major_accounts, today, progress=None)` | `StatementHistory` of the major accounts, or None. |
| `financial_statement(company, resolved, *, request, fetch_full_statements, today, progress=None)` | `StatementHistory` of one full statement, or None. |
| `indicator_history(company, resolved, *, years, fetch_indicators, today, progress=None)` | `StatementHistory` of published indicators, one column per fiscal year, or None. |
| `latest_holdings(company, resolved, *, fetch_investments, today, progress=None)` | `Holdings` of the newest candidate period with an investment table, or None. |
| `latest_preliminary(company, *, search_disclosures, open_filing, today, progress=None)` | `PreliminaryRelease` from the newest KRX fair disclosure in 120 days, or None. |
| `compare_peers(companies, *, request, fetch_peer_accounts, fetch_peer_indicators, today, progress=None)` | `PeerComparison` for the newest period with data for the most companies, or None. |

`HistoryRequest` holds `basis` (`auto`, `consolidated`, or `separate`) and `years`, the reports to chain;
`StatementRequest` adds `statement` (`income`, `balance`, `cash_flow`, `comprehensive_income`, or `equity_changes`);
`PeerRequest` holds `metrics` (`key_accounts`, `ratios`, or `both`), `period`, `fiscal_year`, and `basis`. Lower-level
pieces are public too: `company_indicators`, `peer_indicators`, and `fetch_holdings` read one period, and
`quarter_lines` lays preliminary earnings out by quarter with derived growth and margins.

A `StatementHistory` has the newest period with data (`ref`), the merged `report`, `derived` metrics, and `notes`. A
`Report` holds `lines`, the `filings` they come from, the `basis` used, and the `currency`. Each `Line` has `values`
and `cumulative` amounts by `PeriodRef` and a `rank` in reading order, since full statements arrive sorted by account
ID; lines ranked below `STATEMENTS[kind].key_limit` are the statement's key accounts. The data rules are:

- **Amounts.** Values stay as filed, as integers in the report's `currency` (normally KRW); fractional per-share
  amounts are floats. Per-share lines carry `kind="per_share"` and indicators `kind="percent"`. Nothing is scaled for
  display. Blank, dash, and overflowing (`#########`) cells are None.
- **Periods.** An annual report covers three fiscal years, so annual chains step three years; other periods step one.
  Quarterly income and comprehensive-income lines hold three-month amounts in `values` and year-to-date amounts in
  `cumulative`; quarterly cash flows and equity changes are year to date; quarterly balance sheets compare with the
  prior fiscal year end.
- **Restatements.** Reports merge newest first, and an older report only fills periods the newer ones lack.
- **Basis.** `auto` prefers consolidated statements and falls back to separate ones; chained reports use the basis the
  newest report used, so columns never mix them.
- **Derived metrics.** Growth, operating and net margins, debt-to-equity, and the current ratio are percentages rounded
  to two decimals, computed from year-to-date amounts (`quarter_lines` uses three-month amounts and adds
  quarter-on-quarter growth). A metric is left out when an input is missing or its base is not positive.
  `opendart_analysis.financials.derived.note` names the formulas.
- **Indicators.** OpenDART publishes them from fiscal 2022, in percent, turnover ratios included, on year-to-date
  amounts (`PERCENT_NOTE`); `KEY_INDICATORS` gives key indicators clear labels and stable keys.
- **Provenance.** Results carry the filing numbers they come from; `notes` explain period fallbacks and missing years.

Every workflow bounds its upstream calls: at most three candidate periods are probed, `years` is 1 to `MAX_REPORTS`
(10), a comparison covers 1 to `MAX_PEERS` (100) companies, and the preliminary search reads one page and opens at most
three disclosures. Requests outside the bounds raise `ValueError`. Chained reports and indicator categories are fetched
concurrently; the first failure is raised unchanged after the others finish.

| Callable | Query | SDK method |
| --- | --- | --- |
| `FetchMajorAccounts` | `ReportQuery` | `financial_statements.fnltt_singl_acnt` |
| `FetchFullStatements` | `StatementQuery` (adds `scope`, `CFS` or `OFS`) | `financial_statements.fnltt_singl_acnt_all` |
| `FetchPeerAccounts` | `PeerQuery` (`corp_codes`) | `financial_statements.fnltt_multi_acnt` |
| `FetchIndicators` | `IndicatorQuery` (adds `category`) | `financial_statements.fnltt_singl_indx` |
| `FetchPeerIndicators` | `PeerIndicatorQuery` | `financial_statements.fnltt_cmpny_indx` |
| `FetchInvestments` | `ReportQuery` | `periodic_reports.otr_cpr_invstmnt_sttus` |
| `SearchDisclosures` | `DisclosureQuery` (subtype `I002`, without a disclosure type) | `disclosures.search` |
| `OpenFiling` | a filing number, without volatility, since filed documents do not change | `disclosures.document`, then `parse_filing` |

Pass `str(query.fiscal_year)` and `query.report_code` to the SDK, and a list of `corp_codes`. The record Protocols
(`MajorAccountRecord`, `StatementRecord`, `PeerAccountRecord`, `IndicatorRecord`, `InvestmentRecord`) use the SDK's
field names, so return `response.list` as it is. Workflows state volatility with `period_volatility`: `high` until two
weeks after a period's filing deadline, then `low`; a multi-company request is `high` while any company's window is
open. `OpenFiling` returns None when a filing cannot be opened, and the preliminary workflow skips it with a note.

`compare_peers` raises `PeriodUnavailableError` when the period has not ended or predates 2015, and
`indicator_history` and `compare_peers` raise `IndicatorsUnavailableError`, a `MissingDataError` with `fiscal_year`
and `first_indicator_year`, when only indicators are wanted for a period before fiscal 2022. `compare_peers` raises
`NotConfiguredError` when the data access its `metrics` need is missing.
