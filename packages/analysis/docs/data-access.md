# Data access

Part of the [opendart-analysis guide](../README.md).

Workflows that need OpenDART data never receive an SDK client. Each one takes the upstream operations it needs as
keyword-only async callables, typed by callback Protocols in `opendart_analysis.upstream`, and the caller binds them to
any source: the SDK, a cache, a database, or test data. The clock is an explicit input too: workflows take `today`, the
current date in Korea, which defines OpenDART's filing dates (`opendart_analysis.reports.today_kst()` computes it).

| Export | Shape |
| --- | --- |
| `SearchFilings` | `async (query: FilingQuery, /, *, volatility: Volatility) -> Sequence[FilingRecord] \| None` |
| `FilingQuery` | `corp_code`, `start`, `end` (filing dates, inclusive), `group` (`DisclosureGroup`), `final_only`, `limit` (1-100). |
| `FilingRecord` | Protocol with `report_title` and `filing_number`, both `str \| None`. |
| `Volatility` | `low`, `medium`, or `high`. |
| `DisclosureGroup`, `MAX_FILING_PAGE` | OpenDART disclosure types `A` to `J` (`A` is periodic reports), and 100. |

The contract for every callable:

- **Records.** A callable returns records that workflows read through Protocols naming only the fields they use. The
  field names follow the SDK's models, such as `report_title` for upstream `report_nm`, so SDK records satisfy them as
  they are and are never copied or mutated. Any object with those attributes works. The MCP server's type check proves
  that the SDK's records satisfy the Protocols, but a package resolver cannot, so **install matching versions of
  `opendart-analysis` and `opendart-sdk`**; both are released together with the same version number.
- **No data.** A callable returns `None` when the source has no data, which OpenDART reports as status 013 and the SDK
  raises as `NoDataError`. A workflow treats `None` and an empty sequence alike.
- **Volatility.** Every call says how quickly the requested data can change, from what the workflow knows about it: a
  filing search is `high`, and a period's statement data is `high` until two weeks after its filing deadline, then `low`.
  The source decides whether and how long to cache; analysis keeps no cache and knows no lifetimes.
- **Failures.** Exceptions raised by a callable reach the caller unchanged. Analysis never catches, wraps, or retries
  them, so it adds no second retry layer to the source's own policy.

| `Volatility` | Meaning | MCP server's cache lifetime |
| --- | --- | --- |
| `low` | Final data that changes only through occasional corrections, such as company profiles. | 24 hours |
| `medium` | Records that accumulate during the day but rarely change once filed, such as event reports. | 1 hour |
| `high` | Data that any new filing can change, such as filing searches. | 15 minutes |

A caching source should recheck "no data" answers at least as often as `high` data, because no data may only mean
"not filed yet"; the MCP server caps them at 15 minutes.

Workflows raise exceptions from `opendart_analysis.errors` for requests they cannot answer. Each category has its own
base class, and capabilities raise subclasses whose attributes describe the request. Messages are safe to show to a
user or a model: they hold no credentials or upstream response text and never name a tool or tell anyone to restart a
server.

| Exception | Meaning |
| --- | --- |
| `AnalysisError` | Base for every expected analysis failure. |
| `MissingDataError` | The request cannot have data, such as a period that has not ended yet. |
| `DataSourceError` | Data access failed or answered unusably; `operation` names it. Raise it from a callable when you want one exception family. |
| `NotConfiguredError` | A dependency the request needs was not supplied; `dependency` names it. |

This recipe binds the filing search to a caller-owned SDK client. `or_none` translates the SDK's `NoDataError` to
`None`; it also serves any other SDK call that a workflow probes, as the [periodic reports](reports.md) example
shows:

```python
from collections.abc import Awaitable, Sequence
from opendart import NoDataError, OpenDART
from opendart_analysis.upstream import FilingQuery, FilingRecord, SearchFilings, Volatility


async def or_none[T](call: Awaitable[T]) -> T | None:
    try:
        return await call
    except NoDataError:
        return None


def sdk_filing_search(client: OpenDART) -> SearchFilings:
    async def search_filings(
        query: FilingQuery, /, *, volatility: Volatility
    ) -> Sequence[FilingRecord] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(
            client.disclosures.search(
                corporation_code=query.corp_code,
                filing_start_date=f"{query.start:%Y%m%d}",
                filing_end_date=f"{query.end:%Y%m%d}",
                disclosure_category=query.group,
                final_reports_only="Y" if query.final_only else None,
                page_size=query.limit,
            )
        )
        return None if response is None else response.list

    return search_filings
```

Other SDK failures, such as an exhausted quota, propagate as SDK exceptions. The SDK makes one attempt per call; add
caching or retries in the callable if the application needs them.
