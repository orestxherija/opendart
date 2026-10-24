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
