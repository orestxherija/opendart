# Company profiles

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.profile` turns OpenDART's company overview (`disclosures.company`) into reference facts and finds
the company's latest periodic report, which defines what `latest` means for periodic data (see
[periodic reports](reports.md)). The overview is an input, not a callable, because an application usually reads it
anyway for the fiscal year-end month. With `or_none` and `sdk_filing_search` from the
[data-access recipe](data-access.md):

```python
import asyncio
from dataclasses import dataclass
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.profile import profile_company
from opendart_analysis.reports import today_kst


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    async with OpenDART(settings) as client:
        overview = await or_none(client.disclosures.company(corporation_code="00126380"))
        month = (overview.acc_mt or "") if overview else ""
        samsung = Company("00126380", int(month) if month.isdigit() else 12)
        profile = await profile_company(
            samsung,
            overview,
            search_filings=sdk_filing_search(client),
            today=today_kst(),
        )
    print(profile.facts.ceo, profile.facts.established, profile.facts.fiscal_year_end_month)
    report = profile.latest_report
    print(report.title if report else profile.notes)


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `profile_company(company, overview, *, search_filings, today)` | A `CompanyProfile` for a company with `corp_code` and `fye_month` (`FiscalCompany`). |
| `CompanyProfile` | `facts`, `latest_report` (`PeriodicReport` or None), `sources` (its filing), and `notes`. |
| `company_facts(overview, fye_month)` | `CompanyFacts` from an overview, or only the fiscal year-end month without one. |
| `CompanyFacts` | `stock_name`, `ceo`, `industry_code`, `fiscal_year_end_month`, `established`, `address`, `website`, `ir_url`, `phone`, `fax`, and the corporate and business registration numbers. |
| `CompanyOverview` | Protocol for the overview fields read, with the SDK's names (`ceo_nm`, `est_dt`, `adres`, ...). |
| `NO_OVERVIEW`, `NO_REPORT` | The notes for a missing overview and a missing periodic report. |

Facts are text as filed with whitespace collapsed; blanks and `-` become None, and the establishment date is parsed.
Pass None for the overview when OpenDART has none (status 013). The latest report is the newest final periodic report
filed in the last 15 months, found with one filing search of `high` volatility; failures of `search_filings` reach the
caller unchanged.
