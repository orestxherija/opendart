# Filing discovery

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.filings` searches OpenDART's filing index for one company or the whole market, by category, listing
market, and title text, and returns one slice of the results newest first. Searches read pages through a
`ReadFilingPage` callable, which follows the [data-access convention](data-access.md) and serves exactly one upstream
page. This recipe binds it to a caller-owned SDK client, with `or_none` from the data-access recipe:

```python
import asyncio
from datetime import date
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.filings import (
    DateWindow,
    FilingPage,
    FilingPageQuery,
    FilingSearchRequest,
    ReadFilingPage,
    find_filings,
)
from opendart_analysis.upstream import Volatility


def sdk_filing_pages(client: OpenDART) -> ReadFilingPage:
    async def read_filing_page(
        query: FilingPageQuery, /, *, volatility: Volatility
    ) -> FilingPage | None:
        del volatility  # This recipe caches nothing.
        return await or_none(
            client.disclosures.search(
                corporation_code=query.corp_code,
                filing_start_date=f"{query.start:%Y%m%d}",
                filing_end_date=f"{query.end:%Y%m%d}",
                final_reports_only="Y" if query.final_only else None,
                disclosure_category=query.group,
                disclosure_subcategory=query.subtype,
                corporation_type=query.corporation_type,
                page_number=query.page,
                page_size=query.page_size,
            )
        )

    return read_filing_page


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    window = DateWindow(date(2026, 9, 1), date(2026, 10, 22))
    request = FilingSearchRequest(
        "00126380", window, categories=("major_issues", "exchange_disclosures"), limit=20
    )
    async with OpenDART(settings) as client:
        results = await find_filings(request, read_page=sdk_filing_pages(client))
    for filing in results.filings:
        print(filing.filed, filing.category, filing.title, filing.dart_url)
    print(results.total, results.has_more)


asyncio.run(main())
```

| Export | Purpose |
| --- | --- |
| `find_filings(request, *, read_page, max_calls=20, title_scan_calls=5, page_size=100, progress=no_progress)` | One slice of a search as `FilingResults`. |
| `FilingSearchRequest` | `corp_code` (None for every company), `window`, `categories`, `market`, `title_contains`, `final_only` (default True), `offset`, and `limit` (1-100). |
| `FilingResults` | `filings`, `total` (when known), `has_more`, and `title_scan` when a title filter stopped early. |
| `Filing` | Filing number, `filed` date, filer (`corp_code`, `corp_name`, `stock_code`, `market`), cleaned `title`, `submitter`, `category`, `is_amendment`, `corrected_later`, `withdrawn`, and `dart_url`. |
| `ReadFilingPage`, `FilingPageQuery`, `FilingPage`, `ListedFiling` | The page callable, its query, and the page and row Protocols, which the SDK's `ListResponse` satisfies. |
| `category_codes`, `disjoint_categories`, `infer_category` | Upstream codes for a category, duplicate-free requests, and a category from a title and filing number. |
| `SearchBudgetError`, `TitleScan` | A merged slice that needs too many page reads; how far a title filter reached. |
| `filing_from`, `CATEGORY_INFO`, `FILING_CATEGORIES` | Normalize one row; the 30 categories with their codes and descriptions. |

OpenDART's search takes one category per request and sorts by filing date and time, newest first. Filing numbers do not
follow that order within a day, so results are never sorted by number:

- **One category without a title filter** reads only the pages that cover the slice (two at most) and reports
  OpenDART's exact total. Rows without a valid filing number or a corporation code are skipped.
- **Several categories, or a title filter,** read each category's pages round by round and merge them by filing date,
  then by position within each query, keeping each filing once. A filing is returned only when no unread row can precede
  it, so consecutive slices partition one stable order. Queries already read further back than the others wait.
- **Budgets.** A merged slice may take `max_calls` page reads (at least one per category); past that, `find_filings`
  raises `SearchBudgetError` with `offset`, `limit`, and `max_calls`. A title filter reads at most `title_scan_calls`
  pages and then returns what matched with `title_scan` (filings matched and the oldest date reached). Before every
  query is read in full, `total` is the sum of OpenDART's counts without a title filter and unknown with one.
- **Categories.** A subtype whose group is also requested is dropped. OpenDART filters by subtype only when the group is
  omitted, so `category_codes` sends a subtype alone. Without requested categories, each filing's category is inferred
  from its title and number where that is unambiguous: periodic reports, exchange disclosures, and official form names.

Every page is read with `high` volatility. A search without a company may cover at most three calendar months, which
`FilingSearchRequest` checks. `progress` receives "Searching filings: 4 result pages read" after each merged round.
