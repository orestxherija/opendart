# OpenDART MCP server: implementation plan

Status: implemented (2026-10-22). This plan implements [COMPONENT_DESIGN.md](COMPONENT_DESIGN.md) and
[FILING_DOCUMENTS.md](FILING_DOCUMENTS.md) on FastMCP 4. It records the decisions taken while researching FastMCP, the
architecture and contracts every module codes against, and how the work is split between parallel streams.

Since 2026-10-24 the reusable logic lives in [opendart-analysis](../../analysis/README.md), and MCP services are
adapters over it. The architecture and contracts below describe the current code. The execution waves and the deviations
record how the server was first built, when today's analysis modules were still MCP subpackages.

## Decisions

| Topic | Decision | Why |
| --- | --- | --- |
| Framework | `fastmcp[tasks]>=4.1.2,<5` replaces the `mcp` SDK's `MCPServer`; `mcp>=2.3,<3` stays and is upgraded together with FastMCP. | FastMCP 4 is the only line built on `mcp` 2.x and the 2026-07-28 protocol. It adds middleware, background tasks, component versions, MCP Apps metadata, an in-memory test client, and OpenTelemetry spans. The workspace resolves it without dropping a pin (73 packages). |
| Registration | Standalone decorators (`fastmcp.tools.tool`, `fastmcp.resources.resource`, `fastmcp.prompts.prompt`) in component modules; one ordered registration list in `app/registry.py`. | `tools/list` order is registration order, which keeps prompt caches warm. Ruff's `runtime-evaluated-decorators` understands standalone decorators, so annotation imports stay at runtime. |
| Text and structured output | `markdown_view(render)` wraps each tool: Markdown text for the model, the Pydantic result as `structuredContent`, `outputSchema` generated from the return type. Structured content drops `None` fields. | Hosts that read `content` get compact tables. Claude Code passes `structuredContent` to the model instead, so concise structured output must also be small and labeled. |
| Versions | Every tool, resource, template, and prompt declares `version="MAJOR.MINOR.PATCH"`, starting at `1.0.0`. | Requested by the project; FastMCP publishes it as `_meta.fastmcp.version`, and clients can pin it with `_meta.fastmcp.version` on requests. |
| Fingerprints | `packages/mcp/components.lock.json` records each component's version, SHA-256 of its wire definition, and token estimates; `scripts/mcp/check_mcp_components.py` fails CI when a definition changes without a version bump, when a bump is smaller than the schema change requires, or when tool definitions exceed 10K tokens. | FastMCP and the protocol have no built-in fingerprinting; this makes every definition change explicit and reviewable. |
| Background tasks | `TasksExtension(url="memory://")` with `concurrency=4`; `read_filing`, `get_corporate_events`, and `get_corporate_action_calendar` use `TaskConfig(mode="optional")`. | Optional mode runs in the foreground for hosts without the tasks extension (all Claude hosts today) and as a task for clients that have it. Deadlines and progress heartbeats make the foreground path work on its own. |
| Progress | `ctx.report_progress` through a monotonic `Reporter`, at least every 5 s during waits. | The only progress API that reaches foreground clients; in tasks it becomes `statusMessage`. |
| Apps | Self-contained HTML apps on `ui://opendart/financials.v1.html`, `peers.v1.html`, `calendar.v1.html`, linked from `get_financials`, `compare_companies`, `get_corporate_action_calendar`. No Prefab. | Wide tables and calendars benefit from client-side sorting and filtering. Prefab would replace the typed structured content and load code from a CDN. |
| Middleware | `UsageMiddleware` (per-component counts, latency, errors, upstream calls) and `ServerErrorMiddleware` (domain errors to `ToolError`/`ResourceError`/`PromptError`), plus FastMCP's `StructuredLoggingMiddleware` and a generous `RateLimitingMiddleware`. | `ResponseCachingMiddleware` never caches task results and `ResponseLimitingMiddleware` strips output schemas; the gateway cache covers both needs. `ErrorHandlingMiddleware` logs expected errors as failures. |
| Pagination | Result paging in tools (`limit`, `page`, `has_more`, `next_call`; character offsets in `read_filing`). List pagination stays configurable and off. | 13 tools fit one page, and some hosts do not follow list cursors. |
| Cache hints | Server-wide `cache_ttl` (default 300 s, private scope). | FastMCP 4.1 has no per-resource hints; status reads may lag by the TTL. |
| Disambiguation | `ToolError` with candidates everywhere; elicitation (modern guard pattern and legacy `ctx.elicit`) when the host supports it, behind `tools.elicit_ambiguous_company`. | Resolves design open decision 2 without breaking hosts that lack elicitation. |
| Directory | Background load with a disk cache (`~/.cache/opendart-mcp/corpcode.zip`), daily refresh, stale-while-refresh; corp codes work before it is ready. Loading is `opendart_analysis.directory.DirectoryLoader`; `services/directory.py` configures it and translates failures. | A live download of the 3.6 MB archive took 233 s. |
| Name languages | `corp_name` is Korean, `corp_eng_name` English (99%); both are indexed. | Resolves design open decision 1 from the live directory: 119,717 records, 4,001 listed, 66 alphanumeric stock codes, and stale duplicate listed names that recency breaks ties for. |

## Architecture

Imports point down the table, except that the composition root (`core/runtime.py`) builds services and
`core/upstream.py` uses `core/sdk_binding.py`. `opendart-analysis` imports neither FastMCP, the SDK, nor
`opendart_mcp`; [`importlinter.toml`](../../../importlinter.toml) enforces it.

| Layer | Packages | Role |
| --- | --- | --- |
| Wiring | `server.py`, `app/`, `tools/`, `resources/`, `prompts/`, `apps/`, `completions.py`, `instructions.py` | FastMCP decorators, schemas, descriptions, versions, middleware, elicitation, progress, deadlines, lifespan |
| Services | `services/` | Adapters per component: resolve the company, call an analysis workflow, translate its exceptions, and project its result into output models with concise or detailed selection; callable from tests without MCP |
| Infrastructure | `core/` | Gateway, cache lifetimes, errors, state, runtime, and the SDK binding of analysis data access (`core/upstream*.py`) |
| Output | `models/`, `render/` | Pydantic output models and Markdown renderers, including display units |
| Library | `opendart_analysis` in `packages/analysis`: `documents`, `directory`, `domain`, `catalog`, `reports`, `extracts`, `financials`, `events`, `filings`, `ownership`, `capital`, `debt`, `dividends`, `profile`, `governance`, `calendar` | Parsing, resolution, normalization, service metadata, and analysis workflows over caller-supplied data access |

Every handwritten file stays under 500 lines (loq). Tool modules hold the decorated function and its docstring only;
the service, model, and renderer live in their layers.

### Request path

1. FastMCP validates arguments against the input schema (`additionalProperties: false`).
2. Middleware: structured access log, rate limit, usage metrics, error translation.
3. The tool resolves dependencies: `state: AppState = Depends(get_state)` and `ctx: Context = CurrentContext()`.
4. The service resolves the company (`state.companies.resolve`), calls an analysis workflow with data access bound to
   the gateway (`core.upstream*`), and projects the result into an output model.
5. `markdown_view` renders text and returns `ToolResult(content=markdown, structured_content=model)`.

## Contracts

### State and dependencies

- `core.runtime.open_state(settings, *, api, transport, clock)` builds `AppState`: gateway, response cache, directory
  service, company resolver, document store, clock. The FastMCP lifespan yields `{"state": state}`.
- `app.state.get_state(ctx: Context = CurrentContext()) -> AppState` is the typed dependency for every component.
- `state.require_gateway()` raises the "configure the API key" error when no key is set.

### Upstream access

- `await gateway.call(ttl, gateway.sdk.<resource>.<method>, **kwargs) -> Response | None`. `None` means OpenDART
  status 013 (no data), which is a normal empty answer. TTL constants live in `core.ttl` (`DAY`, `HOUR`, `FILINGS`).
- The gateway caches by method and arguments (bounded by record count), coalesces identical in-flight calls, limits
  concurrency (5), retries transient failures once, never retries quota (020) or maintenance (800), and counts calls
  per KST day.
- Never call the SDK directly from services; never retry in services.
- Workflows in `opendart-analysis` receive typed data-access callables instead of the gateway. `core.upstream` binds
  each one to `gateway.call` with unchanged arguments, and `core.ttl.lifetime` maps the call's `Volatility` hint
  (`low`, `medium`, `high`) to `DAY`, `HOUR`, or `FILINGS`.
- Capability bindings follow the same pattern in `core.upstream_financials`, `core.upstream_filings`, and
  `core.upstream_ownership`; debt, dividends, and governance read catalog services through
  `core.upstream.service_fetch`.

### Errors

- Services raise `core.errors` exceptions with instructive messages (`ConfigurationError`, `InvalidArgumentError`,
  `CompanyNotFoundError`, `AmbiguousCompanyError`, `DirectoryUnavailableError`, `UpstreamError`,
  `QuotaExhaustedError`). `ServerErrorMiddleware` converts them; the text always reaches the model.
- Raise from a `message` variable (`message = f"..."; raise X(message)`) to satisfy ruff's EM and TRY rules.
- Unexpected exceptions are masked (`mask_error_details=True`) and logged.
- Adapters translate `opendart_analysis.errors.AnalysisError` with `core.errors.from_analysis`, which keeps the
  message: `DataSourceError` becomes `UpstreamError`, `NotConfiguredError` becomes `ConfigurationError`, and other
  analysis errors become `InvalidArgumentError`.

### Arguments

Shared `Annotated` aliases in `app/params.py` keep schemas consistent and short: `CompanyArg`, `CompaniesArg` (1–20),
`PeriodArg` (`latest`, `FY`, `Q1`, `H1`, `Q3`), `FiscalYearArg`, `BasisArg`, `UnitArg`, `ResponseFormatArg`,
`SinceArg`, `UntilArg`, `LimitArg`, `PageArg`. Parameter descriptions stay under about 15 words; the conventions are
explained once in `opendart://reference/vocabulary` and the server instructions.

### Results

- Output models subclass `models.common.ToolOutput` or `CompanyOutput`: `company`, `as_of` (KST date),
  `source_filings`, `notes`, then the payload. Paged results carry `pagination` with the exact `next_call`.
- Amounts are integers in won inside models; `unit` scales only the rendered text and the concise view
  (`million_krw` default, one decimal). Ratios and per-share values are never scaled.
- `response_format="concise"` returns decision-relevant fields; `"detailed"` adds every labeled field and raw strings.
- Renderers in `render/` use `render.markdown` helpers and end with `footer(result)`.

### Periods

`opendart_analysis.reports` holds the period logic, and `services.periods` adapts only `resolve_period`.
`services.periods.resolve_period(state, company, period, fiscal_year)` returns the fiscal year, report code, period end,
and the periodic report that defines `latest`. It searches the company's periodic reports first and falls back to
deadline-based candidates; services call `opendart_analysis.reports.first_available(resolved, fetch)` to probe a
`ResolvedPeriod`'s candidates until one has data.

### Progress and deadlines

- `app.progress.Reporter(ctx)` sends strictly increasing integer progress with a message (`"7/20 Samsung Electronics"`).
- `app.progress.with_heartbeat(reporter, awaitable, label=..., deadline=...)` reports every 5 s and raises an
  actionable error at the deadline while the shared work continues and fills the cache.
- Task-enabled tools enforce their own deadlines (the decorator `timeout=` is ignored in tasks): 40 s in the
  foreground, 110 s as a task. They log with `logging`, never `ctx.info()`.

## Components

| Component | Module | Service | Stream |
| --- | --- | --- | --- |
| `find_company`, `get_company_profile` | `tools/company.py` | `services/companies.py` (messages in `services/company_messages.py`) over `opendart_analysis.domain`, `services/profile.py` over `opendart_analysis.profile` | Foundation |
| `search_filings` | `tools/filings.py` | `services/filings.py` over `opendart_analysis.filings` | A |
| `read_filing` (task) | `tools/documents.py` | `services/documents.py` over `opendart_analysis.documents` | A |
| `get_financials` | `tools/financials.py` | `services/financials.py`, `statement_views.py` over `opendart_analysis.financials` (`preliminary` from stream A) | B |
| `compare_companies` | `tools/compare.py` | `services/compare.py`, `peer_table.py` over `opendart_analysis.financials.compare_peers` | B |
| `get_corporate_events` (task) | `tools/events.py` | `services/events.py` over `opendart_analysis.events` | C |
| `get_corporate_action_calendar` (task) | `tools/calendar.py` | `services/calendar.py`, `calendar_items.py`, `calendar_debt.py` over `opendart_analysis.calendar` | C |
| `get_ownership`, `get_capital_structure` | `tools/ownership.py`, `tools/capital.py` | `services/ownership.py`, `control.py`, `holdings.py`, `services/capital.py` over `opendart_analysis.ownership` and `opendart_analysis.capital` | D1 |
| `get_debt_profile`, `get_dividends`, `get_governance` | `tools/debt.py`, `tools/dividends.py`, `tools/governance.py` | matching services over `opendart_analysis.debt`, `.dividends`, and `.governance` | D2 |
| `list_services`, `call_service` (off by default) | `tools/services.py` | `services/catalog.py` over `opendart_analysis.catalog`, SDK binding in `core/sdk_binding.py` | E |
| Company and filing resources | `resources/company.py`, `resources/filings.py` | streams' services | A |
| Reference and status resources | `resources/reference.py`, `resources/status.py` | `opendart_analysis.catalog`, `opendart_analysis.domain` | E |
| 11 prompts, completions, instructions | `prompts/`, `completions.py`, `instructions.py` | | E |
| Middleware, manifest, CI, container | `app/middleware.py`, `manifest.py`, `scripts/` | | F |
| Apps | `apps/` | | F, after B and C |

Resources follow the design table, plus the three `ui://` app resources. Every component declares `version="1.0.0"`,
a `title`, tags (`identity`, `filings`, `documents`, `financials`, `events`, `ownership`, `capital`, `credit`,
`governance`, `reference`, `workflow`, `escape-hatch`), and read-only annotations.

## FastMCP conventions

- Tools: `@tool(name=..., version="1.0.0", title=..., tags={...}, annotations=READ_ONLY)` above
  `@markdown_view(render_x)`; `async def`; keyword parameters with `Annotated` types; `ctx: Context = CurrentContext()`
  and `state: AppState = Depends(get_state)` last. Task-enabled tools add `task=TASK_OPTIONAL`.
- Descriptions: only the docstring text before `Args:` reaches the model. Write 60–120 words of guidance there: what
  the tool answers, when to use it instead of a sibling tool, and notable limits. No dates or other volatile text.
- Resources: pass `description=` and `mime_type=` explicitly (FastMCP uses the raw docstring and defaults to
  `text/plain`); return JSON text, Markdown, or `ResourceResult`, never a model.
- Prompts: modules without `from __future__ import annotations` (ruff `I002` ignored there), plain `str` arguments
  described in `Args:`, at most about 300 words of instructions.
- Tests use the in-memory client: `async with Client(create_server(...)) as client` with a `FakeUpstream` transport and
  a synthetic directory, `Client[FastMCPTransport]` for typing, and a unique task queue per test.

## Testing

- Unit tests per pure module and service, with synthetic fixtures only; golden tests for headlines, date extraction,
  normalization, and rendering.
- In-memory protocol tests per component: schema, annotations, version, text and structured output, empty results,
  and every error path. Task-enabled tools are tested in both modes (task client and a client without the extension).
- An offline task suite (resolve "Samsung", latest Q3 income statement, convertible bonds last year) counts upstream
  calls per question through the usage middleware.
- An opt-in live suite, marked `network`, reads real data like the contract tests.
- Coverage target: 90% branch coverage for the package.

## CI and tooling

- `scripts/analysis/generate_mcp_registry.py --check` (`just analysis generated`) keeps the generated service catalog in
  `opendart_analysis.catalog` in sync with the API catalog; the analysis workflow and a pre-push hook run it.
- `scripts/mcp/check_mcp_components.py` checks versions, fingerprints, and token budgets against the lock; `--update`
  rewrites the lock after an intentional change.
- `scripts/mcp/check_mcp.py` checks both protocol eras, the tool list, `/health`, a reference resource, and the
  missing-key error over real HTTP, and still requires 421 and 403 for hostile Host and Origin headers.
- `scripts/mcp/check_mcp_conformance.py` (`just mcp conformance`) runs the pinned official MCP conformance suite
  against a keyless server at the default and 2026-07-28 wires. The baseline in
  `packages/mcp/conformance-baseline.yaml` lists only failures from the suite's fixture components,
  features the server does not offer, and one upstream SDK
  leniency. A pre-push hook and an MCP workflow job (skipped for drafts) run it.
- The MCP workflow, path filters, prek hooks, and `just mcp` recipes gain these checks; FastMCP and `mcp` update in
  one Renovate group.
- The container sets `TOKIO_WORKER_THREADS=1`, `PYTHON_CPU_COUNT=1`, `FASTMCP_SHOW_SERVER_BANNER=false`, and a
  directory cache under `/tmp`; its memory limit is raised after measuring the loaded directory and document cache.

## Execution

| Wave | Work | Runs |
| --- | --- | --- |
| 0 | FastMCP research: core features and CI; background tasks, apps, elicitation | Done |
| 1 | Pure layers (domain, documents, registry) in parallel with the foundation: dependencies, core, services, app wiring, exemplar tools, stubs, test harness | Done |
| 2 | Streams A–F in parallel, each owning its modules and tests | Done |
| 3 | Apps, integration, manifest lock, CI wiring, container measurements, documentation | Done |
| 4 | Independent review, live smoke test, fixes | Done |

Each stream owns its files. Shared configuration files (`ruff.toml`, `typos.toml`, `loq.toml`) take additive edits
only. Streams run tests with `-n0 --no-cov -o cache_dir=/tmp/pytest-cache-<stream>` and type-check only their files
while others are mid-change; the integration wave runs the full suite, mypy, pyrefly, and the lock check.

## Deviations and findings

What implementation changed relative to [COMPONENT_DESIGN.md](COMPONENT_DESIGN.md), and upstream facts it relied on.

- Filing subtypes: OpenDART applies `pblntf_detail_ty` only when `pblntf_ty` is omitted, so subtype categories are
  sent without their group. Download errors (`document.xml`, `corpCode.xml`) arrive as XML status bodies.
- `get_financials` keeps amounts as integer won in structured output in both formats; `unit` scales only the text
  view. `years` counts reports to chain (annual reports are chained three years apart). Quarterly derived metrics use
  year-to-date amounts, which matches OpenDART's own indicators.
- `get_ownership` waits at most 25 s for the 5% holder and insider report lists, which can take over a minute for a
  large company; the snapshot is returned with a note and the lists finish in the cache for the retry.
- The calendar includes debt maturities from the latest periodic reports' issuance records, selected by the
  calendar-only kind `debt_maturity`. Those records list only the securities issued in the latest fiscal year and
  current period, so a note says so and gives each company's corporate bonds due within a year from the maturity
  ladder. Convertible and hybrid debt kinds are read from 36 months before the first calendar date, because their
  conversion and exercise dates come long after the filing; other kinds from 12 months. When a registration
  statement repeats its decision's dates, the decision's item is kept and cites the statement.
- The event kind `overseas_listing` is `overseas_listing_completed`, so it no longer collides with its group name.
- The escape hatch leaves out the three archive services (`document`, `corporation_codes`, `fnltt_xbrl`) and names
  the tool to use instead.
- Cache hints are server-wide (FastMCP 4.1 has no per-resource hints), so the status resource can lag by the TTL.
- Tool definitions cost about 5.4K model-visible tokens (name, title, description, input schema) and about 25K
  including output schemas, which Claude's tool conversion does not send to the model. Advertised schemas are
  compacted (nullable `anyOf` pairs become type lists).
- Memory, measured natively: about 150 MiB after imports (FastMCP's tasks extension and the SDK's models are the
  largest parts) and about 270 MiB peak while the directory is indexed, so the Compose limit is 512 MiB.
- Expected errors from components are logged at INFO without tracebacks, in FastMCP's logs and the access log.

The review pass after implementation changed these:

- OpenDART takes the API key in the query string, and httpx logs request URLs at INFO. The server therefore
  redacts `crtfc_key` in every log handler and keeps the HTTP client loggers at WARNING.
- Filing searches over several categories merge by filing date, then by each category's own order, because filing
  numbers are not chronological across categories. A row is shown only once no unread row can come before it, so
  `next_call` pages neither repeat nor skip rows.
- Periodic-report and statement data for a period still within its filing deadline plus 14 days is cached like
  filing lists (15 minutes) rather than for a day, and so are answers with no data. Calls covering several
  companies use the shortest lifetime among them.
- For a non-December fiscal year, both fiscal-year labels of the newest report's period are tried before older
  periods, because OpenDART's labeling for such companies is unverified.
- When one call names several ambiguous companies, the user is asked about them one at a time. In the 2026-era
  protocol the answers so far travel in `request_state`; legacy hosts get titled options; hosts that cannot elicit
  get the candidates in the error.
- A debt registration that offers several tranches becomes one event per tranche. A major-issue decision whose
  latest filing came more than 7 days after the board date is flagged `possibly_amended` when the filing index
  cannot confirm an amendment.
- `--update` refuses a missing or unreadable component lock (for example one with merge-conflict markers) unless
  `--accept-changes` is given, so a conflict cannot silently re-baseline unbumped changes. The first lock needs it.
- `call_service` checks list parameters (1 to 100 entries) before resolving any company. Splitting a comma-separated
  string keeps legal-form fragments such as `CO,.LTD` with their name.

## Risks

- No Claude host negotiates the tasks extension yet, and one report shows Claude Code sending a 2025-11-25 protocol
  header on 2026-07-28 requests. The foreground path must stand on its own; verify against the Claude Code version in
  use.
- OpenDART is slow and rate-limited by daily quota. Caching, coalescing, the semaphore, and the usage counter keep
  fan-out tools affordable; the escape hatch stays off by default.
- Memory: about 150 MiB after imports and 270 MiB at peak while the directory is indexed, plus the document cache.
  Measure in the container before changing limits.
- FastMCP and `fastmcp-tasks` patch SDK internals, so they upgrade only together with `mcp`, gated by the task tests.
