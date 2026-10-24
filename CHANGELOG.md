# Changelog

## Unreleased

### Added

- The `opendart-analysis` distribution (`opendart_analysis`): filing parsing, company resolution, the service
  catalog, and analysis workflows over caller-supplied data. It depends only on AnyIO, defusedxml, and Pydantic and
  imports neither the SDK nor MCP, so Python applications can install the SDK, analysis, or both without the server.
- The analysis conventions: `opendart_analysis.upstream` defines data access as typed async callables, a
  catalog-keyed `FetchService`, record protocols naming the SDK fields each calculation reads, and `Volatility`
  freshness hints; `opendart_analysis.errors` defines `AnalysisError`, `MissingDataError`, `DataSourceError`, and
  `NotConfiguredError`. Library options are explicit arguments; analysis reads no environment variables.
  `upstream` also defines the `Progress` callback type and `no_progress`, shared by every workflow that reports
  progress; the events, filings, debt, and calendar packages export the `DateWindow` value their requests take.
- Filing documents and company lookup in analysis:
  - `opendart_analysis.documents`: parse, outline, render, page, and search filing archives, read preliminary
    earnings, and cache filings with `DocumentStore`, whose `get` waits for completion unless given a wait budget.
  - `opendart_analysis.directory`: parse and search the corporation-code archive, resolve names and codes to a
    structured `Resolution`, and keep it loaded with `DirectoryLoader`, which has explicit configuration, an
    injectable clock, and `start`/`refresh`/`aclose` ownership.
- Analysis workflows, each with explicit acquisition bounds:
  - `opendart_analysis.catalog`: metadata for all 85 services, field labels and value kinds, service search, and the
    corporate-event vocabulary; the analysis CI job checks that the generated catalog is current.
  - `opendart_analysis.reports` and `opendart_analysis.extracts`: the latest periodic report, requested periods, and
    periodic-report services read with period-based freshness and source filings.
  - `opendart_analysis.financials`: statements over periods with quarterly and year-to-date figures, restatement
    merging, consolidated or separate fallback, and derived growth, margins, and leverage; published indicators;
    equity investments; preliminary earnings; and peer comparison.
  - `opendart_analysis.events` and `opendart_analysis.filings`: interpreted material events read from the filing
    index, and filing searches that merge categories and title scans within page budgets.
  - `opendart_analysis.ownership`, `capital`, `debt`, `dividends`, `profile`, and `governance`: control snapshots,
    free float, holder and insider reports, share counts, treasury stock, capital changes, use of proceeds, debt
    maturity ladders and issuance, dividend histories, company profiles, and audit, board, pay, and workforce facts
    with red flags.
  - `opendart_analysis.calendar`: corporate-action dates and debt maturities for one company or a watchlist.
- Guides for each analysis capability, an analysis contracts page (units, missing data, provenance, ambiguity, task
  ownership, configuration, exceptions, and versioning), an analysis architecture diagram, and installation choices
  in the root README.
- Import Linter contracts in `importlinter.toml`, run by `just boundaries`, a pre-commit hook, and the MCP CI job:
  analysis and the SDK never import each other, MCP, or server frameworks, and pure modules stay below workflows.
- Release checks for three coordinated distributions: six artifacts, MCP's two bounded workspace dependencies, and no
  other workspace dependency edges.
- Installation smoke tests for both wheels and source archives, with a fresh environment per distribution that installs
  only that artifact, resolves workspace dependencies from its metadata, and asserts that packages outside the choice
  are absent.
- Conventional Commit validation and shared SDK, analysis, and MCP version configuration with Commitizen.
- EditorConfig settings aligned with the repository's formatters and file types.

### Changed

- **Breaking:** the SDK classes `OpenDart`, `OpenDartSettings`, and `OpenDartError` are renamed `OpenDART`,
  `OpenDARTSettings`, and `OpenDARTError`.
- `opendart-mcp` now requires `opendart-analysis` alongside `opendart-sdk`. Its services are adapters over analysis
  workflows; tool names, schemas, outputs, messages, cache lifetimes, progress, and deadlines are unchanged, and the
  component lock is unchanged.
- MCP's internal Python modules moved into analysis: `opendart_mcp.documents`, `opendart_mcp.domain`,
  `opendart_mcp.events`, and the service registry (`opendart_mcp.registry`, now `opendart_analysis.catalog`). MCP
  keeps its model-facing messages, the `ResponseFormat` vocabulary, and the SDK binding (`core/upstream*.py` and
  `core/sdk_binding.py`).
- `opendart-mcp` declares `starlette`, which its server imports directly, instead of relying on `mcp` to provide it.
- MCP's remaining service modules no longer re-export analysis names, and adapter modules left without callers
  after the migration (`services/extracts.py`, `event_index.py`, `calendar_reads.py`, and `debt_tables.py`) are
  removed.
