# Debt securities

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.debt` reads a company's debt securities from its periodic reports: corporate bonds, short-term
bonds, commercial paper, hybrid securities, and contingent capital securities outstanding by remaining maturity, and
the record of issues with their coupons, ratings, maturities, and redemption status. Workflows take the company, a
`ResolvedPeriod` from [`resolve_period`](reports.md), the company's names, and the `FetchService` from the
[extracts guide](extracts.md), with `or_none` and `sdk_filing_search` from the [data-access recipe](data-access.md).

The latest debt profile and the issues that mature within a year:

```python
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.debt import DateWindow, debt_profile, maturity_schedule
from opendart_analysis.reports import resolve_period, today_kst


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    samsung = Company(corp_code="00126380", fye_month=12)
    names = ("삼성전자", "SAMSUNG ELECTRONICS CO,.LTD")
    today = today_kst()
    async with OpenDART(settings) as client:
        resolved = await resolve_period(
            samsung,
            period="latest",
            fiscal_year=None,
            search_filings=sdk_filing_search(client),
            today=today,
        )
        fetch = sdk_fetch_service(client)
        profile = await debt_profile(
            samsung, resolved, names=names, fetch_service=fetch, today=today
        )
        schedule = await maturity_schedule(
            samsung,
            resolved,
            window=DateWindow(today, today + timedelta(days=365)),
            names=names,
            fetch_service=fetch,
            today=today,
        )
    if profile is None:
        print("No debt-security tables in the latest report")
        return
    for ladder in profile.ladder:
        buckets = [(bucket.maturity_bucket, bucket.amount) for bucket in ladder.buckets]
        print(ladder.instrument, ladder.total, buckets)
    print(profile.ref.label, profile.figures)
    for issue in profile.issues:
        if issue.redeemed != "yes":
            print(issue.maturity, issue.security, issue.amount, issue.coupon, issue.rating)
    for maturity in schedule.maturities:
        print(maturity.date, maturity.instrument, maturity.face_value, maturity.filing_number)
    print([source.filing_number for source in profile.sources])


asyncio.run(main())
```

| Workflow | Result |
| --- | --- |
| `debt_profile(company, resolved, *, names, fetch_service, today)` | `DebtProfile` of the first candidate period with any debt table, or None. |
| `maturity_schedule(company, resolved, *, window, names, fetch_service, today)` | `MaturitySchedule`: maturities in `window` and the latest corporate-bond ladder. |

A `DebtProfile` holds the period read (`ref`), its `ladder` of instruments with a balance outstanding, every issue in
the record (`issues`, redeemed ones included), `figures` (`total_debt_securities`, `due_within_1y`, and
`due_within_1y_pct`), and the `sources` the rows came from. A `MaturitySchedule` holds `maturities`, the latest
`period` read (None when no report had debt tables), and the corporate `bonds` ladder of that period. The data rules
are:

- **Ladders.** Each balance service files its own maturity columns; `LADDERS` maps them onto common buckets (`<=1y`,
  `1-2y`, `2-3y`, `3-5y`, `5-10y`, `>10y`, and the filed `1-5y` of hybrids and `>3y` of commercial paper), keeping
  only non-zero buckets. The total row is used, or the public and private rows added when it is missing; a lone
  unlabeled row is the total. `filed` keeps every column as filed with its catalog label. An instrument with nothing
  outstanding is left out.
- **Amounts.** Balances and face values stay in won as filed; coupons are percentages. `due_within_1y_pct` is rounded
  to one decimal. Nothing is scaled for display.
- **Issues.** Sorted by maturity, then issue date, unknown dates last. Ratings such as `AA-(S&P), Aa2(Moody's)` split
  into grades and agencies, Korean agency names translated. `issuer` stays as filed; `own` says whether it is the
  company itself, by its `names` without corporate suffixes, and `other_issuer` names subsidiaries only.
- **Maturities.** Issues not fully redeemed that mature within the window, listed once even when several reports
  repeat them, by date and then security type. Partly redeemed issues keep their original face value, since the record
  does not say how much is left. Issuance records cover only recent issues: the latest report's and, for a quarterly
  or half-year report, the previous annual report's. The corporate-bond ladder covers every bond outstanding.
- **Provenance.** `sources` lists each distinct filing number of the rows, titled when it is the report that
  `resolve_period` found.

Each fetch states volatility like [extracts](extracts.md), and failures of `fetch_service` reach the caller
unchanged; the workflows raise no errors of their own. The profile probes at most `probe_attempts(resolved)`
candidate periods, six calls each (`DEBT_SERVICES`). The schedule makes two or three calls per candidate and, when no
candidate has tables, reads the annual report before the first one.

The pieces are public too: `fetch_tables` and `assemble` split the profile into fetching and assembly, and
`build_ladder`, `derive`, `issuance`, `maturities`, `rating`, `redeemed`, `offering`, `company_names`, and
`prior_annual` work on records already fetched. `derive` accepts any ladders with `total` and `buckets`.
