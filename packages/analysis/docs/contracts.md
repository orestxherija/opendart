# Contracts

Part of the [opendart-analysis guide](../README.md).

These rules hold across every capability. Each guide adds the details of its own results; module names below are
under `opendart_analysis`.

## Data units

Analysis returns values in their natural units and never scales them for display.

| Value | Unit | Where |
| --- | --- | --- |
| Money totals | Integer won as filed, or the report's own currency where a filing states one. Values filed in thousands or millions of won are converted to won. | `financials`, `debt`, `capital`, `dividends`, `governance`, `calendar` |
| Per-share amounts | Won per share, often fractional (`int \| float`); never scaled. | `financials` (statement lines with `kind="per_share"`), `dividends` (`KRW/share`) |
| Percentages | Percentage points as filed (`12.5` means 12.5 percent). Derived growth, margins, and leverage are percentages rounded to two decimals. | `financials.derived`, `ownership`, `dividends` (`%`) |
| Ratios and multiples | Dimensionless, as filed, such as merger or split ratios. | `catalog` field kind `ratio` |
| Share and people counts | Integers. | `capital`, `ownership`, `governance` |
| Dates | `datetime.date` in Korean time; filing windows are inclusive. | every workflow |

Two values keep their filed unit by design. Audit fees are filed without a unit, so `governance` infers the scale from
the fee per audit hour and records it in `fee_scale`; when it cannot, the fee stays as filed and `fee_scale` is `None`.
Filing tables in `documents` are never rescaled: the parser translates the table's own unit statement, such as
`(단위 : 백만원)`, and shows it above the table.

The catalog's field kinds (`catalog.specs`) record which upstream fields are money (`amount`), money per share
(`per_share`), counts, percentages, ratios, dates, periods, and codes. Only `amount` fields are meant to be scaled for
display. Display scaling belongs to the presentation layer: the MCP server converts won to million or billion won in
its rendered text with its `unit` argument and leaves structured results in won.

## Missing data

"No data" is an answer, not a failure:

- Caller-supplied data access returns `None` when the source has no data, which OpenDART reports as status 013. A
  workflow treats `None` and an empty sequence alike ([data access](data-access.md)).
- Results report what is absent instead of raising: optional fields are `None` when the filing omits them, sequences
  are empty, and results carry `notes` (or a `note`) where coverage is partial, such as `financials.history`,
  `ownership.report`, `capital.structure`, `profile.latest`, and the document models.
- `reports.first_available` returns `None` when no candidate period has data.
- Partial reads say which parts are missing: `events.fetch_events` lists failed event kinds in `failed`, the calendar
  reports a failed company with its error, `filings.find_filings` reports `has_more`, `total`, and `title_scan`, and
  `financials.compare_peers` reports `coverage`.

`errors.MissingDataError` is reserved for requests that cannot have data at all, such as a period that has not ended
(`reports.PeriodUnavailableError`) or indicators OpenDART does not publish for a period
(`financials.IndicatorsUnavailableError`).

## Provenance

Results name the filings they come from by 14-digit filing (receipt) number, which also opens the original document
through `documents` or the OpenDART viewer.

- `extracts.FilingSource` (`filing_number` and `title`) lists source filings in periodic-report results:
  `profile`, `dividends`, `debt`, `capital`, `ownership`, and `governance`.
- Row-level values carry `filing_number` where rows come from different filings: statement rows in
  `financials.statements`, preliminary earnings, interpreted events, calendar items, and debt maturities.
- Records read through data access are never copied or mutated, so a caller's cached SDK responses stay intact.

## Structured ambiguity

Company resolution never guesses silently. `directory.resolve` returns a `Resolution` with the selected `record`, the
ranked `candidates`, and a `reason`:

| `reason` | `record` | Meaning |
| --- | --- | --- |
| `code` | set | The text was a corporation or stock code. |
| `exact` | set | One company matched the name exactly, or recency broke a tie between exact matches. |
| `dominant` | set | A partial or fuzzy match clearly outranked the others. |
| `ambiguous` | `None` | Several companies match; `candidates` lists them, listed companies first. |
| `not_found` | `None` | Nothing matches; `candidates` is empty. |

Each candidate is a `Match` with its `tier` (`code`, `exact`, `prefix`, `token`, or `fuzzy`). How to present
candidates, whether to ask the user, and what to say are the caller's decisions; the MCP server turns them into its
elicitation and messages. See the [company directory](directory.md) guide.

## Tasks and lifecycle

Importing `opendart_analysis` or any subpackage starts nothing: no tasks, threads, files, network access, or settings.
Only two components own work that outlives a call, and both start it only when used and stop it when closed:

| Component | Owns | Starts | Stops |
| --- | --- | --- | --- |
| `documents.DocumentStore` | One shared download-and-parse task per filing, worker threads for parsing, and a rendered-text cache. | On the first `get` of a filing. | `aclose()` or `async with`. |
| `directory.DirectoryLoader` | One loading and refresh task, worker threads for parsing and cache files, and the cache file at `LoaderConfig.cache_path`. | `start()` or `async with`. | `aclose()` or `async with`. |

Everything else is a function call. Workflows may call data access concurrently within a call, and each one documents
the bound on that fan-out: a request size, such as `financials.MAX_PEERS`; a per-read limit, such as
`events.ReadPolicy.concurrency`; or one limit shared by every call, such as the calendar's `limit`
(`upstream.CallLimit`, five calls by default). They keep no state, cache, or background work between calls. Pure
parsing, such as `documents.parse_filing` and `directory.parse_directory`, is synchronous and can be slow on large
archives, so asynchronous applications run it in a worker thread.

Asynchronous workflows run on asyncio. The store and the loader use `asyncio` tasks and timeouts directly, and
several workflows use `asyncio.gather`, so they do not run under Trio. A caller-supplied client, such as an SDK
`OpenDART` instance, stays caller-owned: analysis never opens or closes it.

## Configuration

Analysis reads no environment variables, configuration files, or global settings. Everything a workflow depends on
is an explicit argument, and every policy has a documented default:

- data access as typed callables, and the current date as `today` (`reports.today_kst()` computes it);
- acquisition bounds, such as `max_calls` and `title_scan_calls` of `filings.find_filings`, `max_companies` and
  `limit` of the calendar, and `events.ReadPolicy` (concurrency, index pages, and which failures to tolerate); request
  sizes are validated against published ceilings such as `financials.MAX_REPORTS` and `MAX_PEERS`;
- runtime settings of the two long-lived components: `DocumentStore` limits (cache size, parallel parses and
  downloads) and timeouts, and `directory.LoaderConfig` (cache path, refresh age, download deadline, and retry delays);
- optional progress callbacks (`upstream.Progress`), async callables that receive short messages;
  workflows default to `upstream.no_progress`, which discards them.

The MCP server keeps its `OPENDART_MCP_*` environment variables and translates them into these arguments, for example
`services/directory.py` builds a `LoaderConfig` from its directory settings. The SDK's `OPENDART_API__*` variables
configure only the SDK client the caller creates.

## Exceptions

| Exception | Raised when |
| --- | --- |
| `errors.AnalysisError` | Base of the expected workflow failures below; the message is safe to show. |
| `errors.MissingDataError` | The request cannot have data. Subclasses: `reports.PeriodUnavailableError`, `financials.IndicatorsUnavailableError`. |
| `errors.DataSourceError` | Data access failed or answered unusably; `operation` names it. Analysis does not raise it itself: data access may, to opt into one family. |
| `errors.NotConfiguredError` | A dependency the request needs was not supplied; `dependency` names it. Raised by `financials.compare_peers`, `capital.capital_structure`, and `DirectoryLoader` without a fetch callback. |
| `directory.DirectoryNotReadyError` | The loader has no directory yet; `status`, `elapsed_s`, and `failure` say why. |
| `filings.SearchBudgetError` | A multi-category search slice needs more page reads than allowed. |
| `calendar.CalendarRequestError` | A calendar request is invalid: `CalendarWindowError`, `UnknownKindsError`, `UndatedKindsError`, or `TooManyCompaniesError`. |
| `documents.DocumentError` | Archive, parsing, navigation, or store failures, such as `ArchiveTooLargeError`, `MalformedArchiveError`, `SectionNotFoundError`, `DownloadPendingError`, and `StoreClosedError`. Derives from `Exception`, not `AnalysisError`. |
| `directory.DirectoryError` | The corporation-code archive is malformed, oversized, or unsafe to parse. Derives from `Exception`. |
| `ValueError` | An argument is invalid in itself, such as a filing window that ends before it starts, a `FilingQuery` limit outside 1 to 100, a non-positive `LoaderConfig` age, a limit below 1 in `ReadPolicy`, `CallLimit`, the calendar's `limit`, or `DocumentStore`'s `max_parallel_fetches`, or an unknown event group or kind in `catalog.expand`. |
| `KeyError` | A catalog lookup names no service: `catalog.service`, `field_spec`, `field_label`, and `field_kind`; the message of `service` suggests close names. |
| `RuntimeError` | A `DirectoryLoader` is used out of order: `start()` or `run()` after `aclose()`, a second concurrent `run()`, or `wait()` while nothing has loaded and no `run()` is in progress: the loader was never started, or its `run()` stopped before the first attempt settled. |

Messages are complete sentences without credentials or upstream response text, and they never name a tool or tell
anyone to restart a server. Callers decide what to do from the exception's type and attributes.

Exceptions raised by caller-supplied data access reach the caller unchanged: analysis never wraps, retries, or
suppresses them, with two exceptions. A partial-result policy the caller chooses, `events.ReadPolicy.tolerate`, which
by default accepts only `DataSourceError`, decides which failures mark an event kind (or a calendar company) as failed
instead of failing the whole read; every other failure propagates. And `DirectoryLoader` never re-raises a failure of
its fetch callback: it records it as a `directory.LoadFailure` in `failure`, retries on its schedule, and `wait()`
reports it as `DirectoryNotReadyError` with that `failure`.

## Versioning

Analysis and the SDK are released together with the same version number. Record protocols name the SDK's model
fields, such as `report_title` for upstream `report_nm`, and the MCP server's type check proves that SDK records
satisfy them. A package resolver cannot check that, so applications that install both should install matching
versions of `opendart-analysis` and `opendart-sdk`.

Public names are the exports of each capability package (`__all__`) and the conventions in `upstream` and `errors`.
Modules under `domain`, and modules a package does not export, are internal and may change. Before 1.0, a minor
release may change public names; the [changelog](../../../CHANGELOG.md) records them.

Annotations are for static type checkers. Modules use postponed annotations (`from __future__ import annotations`) and
import names used only in annotations under `TYPE_CHECKING`, so resolving the annotations of the analysis dataclasses
at runtime, with `typing.get_type_hints` or a Pydantic `TypeAdapter`, is not supported; convert results to your own
models instead. The Pydantic models in `documents`, such as `DocumentInfo`, are the exception and validate as usual.
