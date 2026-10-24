# Filing documents

Part of the [opendart-analysis guide](../README.md).

## Read a filing

Download a filing with the SDK, parse it, inspect its outline, read a section, and search its text:

```python
import asyncio
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.documents import ParsedFiling, parse_filing


async def load_filing(client: OpenDART, filing_number: str) -> ParsedFiling:
    archive = await client.disclosures.document(filing_number=filing_number)
    return await asyncio.to_thread(parse_filing, filing_number, archive)


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    async with OpenDART(settings) as client:
        filing = await load_filing(client, "20260515003117")

    outline = filing.outline()
    for section in outline.sections:
        print(section.id, section.title_en or section.title_ko)

    chunk = filing.read(section="consolidated_notes", max_chars=4000)
    print(chunk.content)

    for hit in filing.search("borrowings").hits:
        print(hit.section_id, hit.snippet)


asyncio.run(main())
```

The application owns the SDK client: it opens it, keeps it for as long as it needs, and closes it. Nothing in this
package opens, closes, or retries a client. Any coroutine that returns the archive bytes works in place of the SDK
call, which is how the tests run this example against a synthetic archive.

Parsing is synchronous and can take a noticeable amount of CPU time on large filings. Asynchronous applications should
run `parse_filing` in a worker thread, as above, or use the [document store](#document-store), which does so for them.
A `ParsedFiling` is immutable apart from renderings it memoizes on first use, so it can be cached and shared.

## Documents API

`opendart_analysis.documents` exports:

| Export | Purpose |
| --- | --- |
| `parse_filing(filing_number, archive, *, limits=None)` | Unpack and parse a ZIP archive into a `ParsedFiling`. |
| `ParsedFiling` | Filing metadata, `outline()`, paged `read()`, `search()`, `section_markdown()`, and `resolve_section()`. |
| `DocumentStore` | Single-flight download, parse, and cache, described [below](#document-store). |
| `extract_preliminary_earnings(parsed)` | Read a KRX preliminary-earnings disclosure, or return None for other filings. |
| `ArchiveLimits`, `read_members`, `Member`, `decode` | Bounded in-memory unpacking and charset decoding. |
| `dart_url(filing_number)` | The English DART viewer link for a filing. |
| `ALIAS_NAMES` | Section aliases, such as `business` or `consolidated_notes`, accepted by `section` in periodic reports. |
| `DEFAULT_MAX_CHARS`, `MAX_CHARS_CAP`, `MAX_HITS` | Page size (8,000), page-size cap (30,000), and search-hit cap (50). |

Results are Pydantic models that reject unknown fields: `Outline`, `ReadChunk`, `SearchResult`, `SearchHit`,
`SectionInfo`, `SuggestedSection`, `DocumentInfo`, `TableData`, `Amendment`, `AmendmentChange`, `DocumentStoreStats`,
and the `PreliminaryEarnings` family (`PreliminaryPeriod`, `PreliminaryRow`, `PreliminaryValue`, `PreliminaryChange`).
`LabelMode` (`english`, `korean`, or `both`), `DocumentFormat` (`dart_xml` or `krx_html`), and `TableLayout` (`grid`
or `form`) are literal types. Offsets and character counts refer to the rendered Markdown in the requested label
language. Other modules, such as the tree builders and markup helpers, are internal.

Every failure inherits `DocumentError`. Messages name sizes, keys, and section IDs, never document text or
credentials, so they are safe to show to a user or a model.

| Exception | Raised when | Attributes |
| --- | --- | --- |
| `ArchiveTooLargeError` | The archive, a member, the expanded total, or the member count exceeds its limit. | `observed_bytes`, `limit`, `measure` |
| `MalformedArchiveError` | The bytes are not a readable, unencrypted ZIP holding DART XML or KRX HTML. | |
| `UnknownDocumentError` | The requested document key, form code, or member name is not in the archive. | `available`, `document` |
| `SectionNotFoundError` | No section matches the requested ID, alias, or heading text. | `query`, `closest` |
| `DownloadPendingError` | A `DocumentStore` wait budget ran out; the work continues and its result is cached. | `filing_number`, `waited_s` |
| `StoreClosedError` | The store is closed, or closed while a caller waited. | |

`read` and `search` raise `ValueError` for a negative offset, a page size or limit below 1, a blank query, or an
unknown label language.

## Archive limits

`read_members` and `parse_filing` check sizes before and during decompression, keep every member in memory, and never
use member names as paths. The `ArchiveLimits` defaults leave headroom over the largest live sample (9.7 MB expanded):

| Field | Default |
| --- | --- |
| `max_compressed_bytes` | 32 MiB |
| `max_member_bytes` | 32 MiB per expanded member |
| `max_total_bytes` | 64 MiB expanded in total |
| `max_members` | 20 |

Pass `limits=ArchiveLimits(...)` to `parse_filing` to change them. Members decode as strict UTF-8 with a CP949
fallback; declared charsets are ignored, because KRX pages declare `euc-kr` but are UTF-8.

## Document store

`DocumentStore` downloads, parses, and caches filings for long-running asynchronous applications. Concurrent callers
for one filing share a single task, which outlives a caller that gives up or is cancelled, and its result is cached.
Filings are immutable, so cached results never expire; the cache is bounded by the rendered characters it holds, and
the most recent filing is always kept.

```python
import asyncio
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.documents import DocumentStore


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    async with OpenDART(settings) as client:

        async def fetch(filing_number: str) -> bytes:
            return await client.disclosures.document(filing_number=filing_number)

        async with DocumentStore(fetch, max_rendered_chars=64 * 1024 * 1024) as store:
            filing = await store.get("20260515003117")
            print(filing.outline().sections[0].title_en)


asyncio.run(main())
```

Ownership and lifecycle rules:

- The store requires an asyncio event loop. It creates plain `asyncio` tasks, so it does not run under Trio, even
  through AnyIO. Create it anywhere and use it from one event loop.
- Close it with `await store.aclose()` or by leaving `async with store:`. Closing cancels unfinished downloads, waits
  for them to stop, and drops the cache; a parse already running in a worker thread finishes first. Callers still
  waiting get `StoreClosedError`, and so does every later `get`.
- The caller owns `fetch` and any client behind it. Close that client after the store, as in the example.
- `get(filing_number, wait_s=None)` waits until the shared task finishes. A float `wait_s` is a host wait budget:
  when it runs out, `get` raises `DownloadPendingError` while the work continues, so a later call finds the result
  cached. `on_progress`, an async callback, receives a message every `progress_every_s` seconds while a caller waits.
- `fetch_timeout_s` (120 s by default; None disables it) bounds each download, so a stalled transfer fails and the
  next caller retries it. Failures reach every waiter and are not cached.
- `max_parallel_fetches` bounds the downloads in flight at once; further filings wait for a slot, and that wait counts
  toward a caller's `wait_s` but not toward `fetch_timeout_s`. None (the default) leaves downloads unbounded, for a
  `fetch` that bounds them itself, as the MCP server's gateway does. A value below 1 raises `ValueError`.
- At most `max_parallel_parses` worker threads (2 by default) parse at once, bounding memory. `parse` replaces
  `parse_filing`, for example to pass custom `ArchiveLimits`.
- `stats()` returns a `DocumentStoreStats` with entries, rendered characters, hits, misses, work in flight, and
  failures.
