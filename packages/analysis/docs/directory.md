# Company directory

Part of the [opendart-analysis guide](../README.md).

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
time on the full archive, so asynchronous applications should run it in a worker thread, as above. Parsing and
search never download, cache, or refresh anything; long-running applications can hand that to the
[loader](#loader). A `Directory` is immutable and keeps its columns packed, so it can be shared freely and the parsed
records dropped once it is built.

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

The MCP server builds on this API: it runs the loader with its own settings, asks the user to choose among
ambiguous candidates when the client supports elicitation, and turns each outcome into model-facing messages that
name its tools.

## Loader

`DirectoryLoader` keeps a current `Directory` for long-running asynchronous applications. OpenDART can take minutes to
send the archive, so the loader works in the background: a cached copy on disk makes restarts immediate, a stale copy
is served while a fresh one downloads, failed downloads are retried with backoff, and the archive is downloaded again
when it reaches its maximum age. The caller supplies the download as an async callback that returns the archive bytes;
the recipe below binds it to a caller-owned SDK client, in the same way as the
[data-access recipes](data-access.md):

```python
import asyncio
from getpass import getpass
from pathlib import Path
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.directory import DirectoryLoader, FetchArchive, LoaderConfig, resolve


def sdk_archive_fetch(client: OpenDART) -> FetchArchive:
    async def fetch_archive() -> bytes:
        return await client.disclosures.corporation_codes()

    return fetch_archive


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")), timeout=90.0)
    config = LoaderConfig(cache_path=Path.home() / ".cache" / "my-app" / "corpcode.zip")
    async with OpenDART(settings) as client:
        async with DirectoryLoader(sdk_archive_fetch(client), config) as loader:
            directory = await loader.wait(600)
            print(resolve(directory, "Samsung Electronics").reason)
            # Later reads of loader.directory see each refreshed archive.


asyncio.run(main())
```

`LoaderConfig` is a frozen value; every field is keyword-only:

| Field | Default | Meaning |
| --- | --- | --- |
| `cache_path` | None | File holding the cached archive; None disables disk caching. |
| `max_age_s` | 86,400 | Archive age after which it is downloaded again. |
| `fetch_timeout_s` | 900 | Overall deadline for one download; None disables it. |
| `retry_delays_s` | 60, 300, 900, 3,600 | Waits between failed initial attempts; the last also follows every failed refresh. |
| `progress_every_s` | 5 | Interval between progress messages while a caller waits. |

The cache file is the archive exactly as downloaded, written to a temporary sibling (`.tmp`) and renamed into place,
and its modification time records when it was downloaded. On start, a cache younger than `max_age_s` is used without
downloading; an older readable one is installed at once and replaced when the download succeeds. An unreadable cache
is ignored, and a cache that cannot be written only disables caching.

Ownership and lifecycle rules:

- The loader requires an asyncio event loop: it uses `asyncio` tasks, timeouts, and worker threads, so it does not run
  under Trio, even through AnyIO. Create it anywhere; importing the package and constructing a loader start nothing.
- `start()`, or entering `async with`, runs the loader in a task it owns. Alternatively, await `run()` in a task the
  application owns and cancel that task to stop it. `run()` loads, then refreshes on schedule until cancelled; without
  a fetch callback it returns after reading the cache.
- `aclose()`, or leaving `async with`, cancels the owned task, including a download in progress, and wakes waiting
  callers. The last directory stays readable. The caller owns the fetch callback and any client behind it; close that
  client after the loader, as in the example.
- `refresh()` downloads now and returns whether a fresh directory was installed; a call made while another refresh
  runs shares its outcome.
- `directory` is the current `Directory`, or None before the first successful load, so callers can keep accepting
  corp codes, or other lookups that need no directory, while it loads. `status` is `loading`, `ready`, `failed`, or
  `disabled` (no fetch callback and no usable cache); `source` is `disk` or `download`.
- `wait(timeout_s=None, *, on_progress=None)` returns the directory, waiting for the first attempt to settle for at
  most `timeout_s` seconds and awaiting `on_progress` with a message every `progress_every_s` seconds. It raises
  `DirectoryNotReadyError` when no directory is loaded after the wait (`status` is `loading` or `failed`, with
  `elapsed_s` and `failure`), or `NotConfiguredError` (`dependency` is `fetch`) without a fetch callback or cache.
- Any exception raised by the fetch callback, including a timeout, is a load failure, never re-raised. `failure` keeps
  the last one as a `LoadFailure` with the `error` itself and a safe `reason`, until a load succeeds. `describe_error`,
  a callable passed to the loader, produces that reason, for example to translate SDK errors; by default it is the
  exception's message, or its type name. An unusable archive is described by its `DirectoryError`, and an unexpected
  error elsewhere is logged and described as `unexpected <type>`.
- `clock`, an aware-datetime callable (UTC by default), measures archive ages and elapsed time.
