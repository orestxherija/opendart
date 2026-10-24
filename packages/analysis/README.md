# OpenDART analysis

[![CI](https://github.com/orestxherija/opendart/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/orestxherija/opendart/actions/workflows/ci.yml?query=branch%3Amain)
[![codecov](https://codecov.io/github/orestxherija/opendart/branch/main/graph/badge.svg?flag=analysis&token=8TTWOC0RC4)](https://codecov.io/github/orestxherija/opendart)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![code style: Ruff](https://img.shields.io/badge/code%20style-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![type check: Pyrefly](https://img.shields.io/badge/type%20check-pyrefly-blueviolet)](https://pyrefly.org/)

Filing parsing, company lookup, and analysis for English OpenDART data. Requires Python 3.14+.

## Table of contents

- [Design](#design)
- [Install](#install)
- [Read a filing](#read-a-filing)
- [Documents API](#documents-api)
- [Archive limits](#archive-limits)
- [Document store](#document-store)
- [Company directory](#company-directory)
- [Maintainer notes](#maintainer-notes)

## Design

The package works on bytes, records, and callbacks supplied by the caller. It needs neither the OpenDART SDK
(`opendart-sdk`) nor the MCP server (`opendart-mcp`), and it never imports either one, so it works with any data
source. Its only dependencies are AnyIO, defusedxml, and Pydantic. The MCP server depends on this package and on the
SDK, and binds the two together.

Capabilities live in subpackages; importing `opendart_analysis` itself loads nothing else.
`opendart_analysis.documents` turns the ZIP archive returned by `disclosures.document` into an outline, paged
Markdown, typed tables, and search results, using the filing's own English headings and labels.
`opendart_analysis.directory` parses the corporation-code archive returned by `disclosures.corporation_codes` and
resolves company names and codes. Modules under `opendart_analysis.domain` are internal.

## Install

From a checkout, run `uv sync --locked --all-packages`. The package can also be installed directly with
`python -m pip install ./packages/analysis` from the repository root. Its distribution name is `opendart-analysis`
and its import name is `opendart_analysis`.

Applications that download filings with the SDK install both distributions, `opendart-sdk` and `opendart-analysis`.

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
- At most `max_parallel_parses` worker threads (2 by default) parse at once, bounding memory. `parse` replaces
  `parse_filing`, for example to pass custom `ArchiveLimits`.
- `stats()` returns a `DocumentStoreStats` with entries, rendered characters, hits, misses, work in flight, and
  failures.

## Company directory

`opendart_analysis.directory` turns OpenDART's corporation-code archive (about 120,000 companies) into a searchable
`Directory` and resolves a free-text reference, such as a name, stock code, or corp code, to one company. Download the
archive with the SDK, parse and index it, then search or resolve:

```python
import asyncio
from datetime import UTC, datetime
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.directory import Directory, company_label, parse_directory, resolve


async def load_directory(client: OpenDART) -> Directory:
    archive = await client.disclosures.corporation_codes()
    loaded_at = datetime.now(UTC)
    records = await asyncio.to_thread(parse_directory, archive)
    return Directory.build(records, loaded_at=loaded_at)


async def main():
    # OpenDART can pause for a while before sending the archive.
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")), timeout=90.0)
    async with OpenDART(settings) as client:
        directory = await load_directory(client)

    for match in directory.search("Hyundai", listed=True, limit=5):
        print(match.tier, company_label(match.record))

    resolution = resolve(directory, "Samsung")
    if resolution.record is not None:
        print("Selected", resolution.record.corp_code)
    elif resolution.reason == "ambiguous":
        for match in resolution.candidates[:5]:
            print("Candidate", company_label(match.record))
    else:
        print("No company matches")


asyncio.run(main())
```

Parsing is synchronous: it streams the XML with defusedxml, which rejects DTDs and entities, and uses noticeable CPU
time on the full archive, so asynchronous applications should run it in a worker thread, as above. Nothing in the
package downloads, caches, or refreshes the directory: the application decides when to fetch a new archive, where to
keep it, and when to rebuild. A `Directory` is immutable and keeps its columns packed, so it can be shared freely and
the parsed records dropped once it is built.

| Export | Purpose |
| --- | --- |
| `parse_directory(archive, *, max_expanded_bytes=...)` | Parse the ZIP into `CorpRecord` values (XML up to 64 MiB). |
| `Directory.build(records, *, loaded_at)` | Index records; `loaded_at` records when the archive was downloaded. |
| `Directory.search(query, *, listed=None, limit=10)` | Ranked `Match` values with `record`, `score`, and `tier`. |
| `Directory.get`, `by_stock_code`, `exact` | Look up by corp code, stock code (including `0068Y0`), or exact name. |
| `resolve(directory, text)` | A `Resolution` with the selected `record`, ranked `candidates`, and a `reason`. |
| `company_label(record)` | A one-line description with the names, codes, and modification date. |
| `CorpRecord` | Corp code, Korean name, English name, stock code, modification date, `listed`, and `display_name`. |

Search runs tiers in order, `code`, `exact`, `prefix`, `token`, then `fuzzy` (`TIER_ORDER`), and matches English and
Korean names in a compact normalized form, so spacing, case, and legal forms such as "Co., Ltd." do not matter.
Results rank by tier, then listed before unlisted, then score, then the shorter matched name, then the more recently
modified record, then corp code.

`resolve` selects a company only when one clearly dominates: a code, a name exactly one listed company has (or a
clearly newer one of several), or a partial or fuzzy name that points to one company. A business-group name such as
"Hyundai" stays ambiguous. Its `reason` keeps the outcomes distinct:

| `reason` | `record` | `candidates` |
| --- | --- | --- |
| `code` | The company with that corp or stock code. | The code match. |
| `exact` | The company whose name equals the query. | Ranked matches considered (at most `CANDIDATE_POOL`, 25). |
| `dominant` | The single company a partial or fuzzy name points to. | Ranked matches considered. |
| `ambiguous` | None. | Ranked matches, listed companies first, for the caller to choose from. |
| `not_found` | None. | Empty. A code that is not in the directory, or a filing number, is never matched by name. |

`parse_directory` raises `DirectoryError` when the bytes are not a readable ZIP, the XML member is missing or larger
than the limit, the XML is malformed or uses DTDs or entities, or most records are invalid. `Directory.search` raises
`ValueError` for a limit below 1. Resolution never raises for an unknown or ambiguous name.

The MCP server builds on this API: it downloads and caches the archive, refreshes it daily by default, asks the user
to choose among ambiguous candidates when the client supports elicitation, and turns each outcome into model-facing
messages that name its tools.

## Maintainer notes

MCP tool and resource output schemas embed the document models and the domain vocabulary, such as `Market`, `Period`,
and `Unit`. Changing their fields, values, defaults, or descriptions is an MCP wire change: run `just mcp components`
and review the component lock before merging. Keep one class per type
rather than copying models into MCP.

Tests use synthetic archives built in `tests/documents/conftest.py` and `tests/domain/conftest.py` and run offline
without the SDK or MCP. `tests/directory/` exercises the directory example above against a synthetic archive.
