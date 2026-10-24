# Changelog

## Unreleased

### Added

- Conventional Commit validation and shared SDK, analysis, and MCP version configuration with Commitizen.
- The `opendart-analysis` distribution (`opendart_analysis`), which depends on neither the SDK nor MCP. Filing-document
  parsing, search, and caching moved from `opendart_mcp.documents` to `opendart_analysis.documents`; MCP now requires
  `opendart-analysis` alongside `opendart-sdk`.
- `opendart_analysis.directory`: parse the corporation-code archive, search it, and resolve company names and codes
  to structured outcomes. The company-domain modules moved from `opendart_mcp.domain` to `opendart_analysis.domain`;
  MCP keeps its model-facing resolution messages and the `ResponseFormat` vocabulary.
- `opendart_analysis.upstream` and `opendart_analysis.errors`: the data-access convention for analysis workflows
  (typed callables, `Volatility` freshness hints, and record protocols) and structured analysis exceptions.
- `opendart_analysis.reports`: find a company's latest periodic report and resolve requested periods. MCP's period
  services now adapt it without behavior changes.
- `opendart_analysis.catalog`: MCP's service registry moved here, with service specs and generated metadata for all 85
  services, field labels and kinds, service search, and the corporate-event vocabulary; values are unchanged.
  `sdk_method` stays in MCP as `opendart_mcp.services.sdk_binding`, and the analysis CI job checks catalog freshness.
- Release checks for three coordinated distributions: six artifacts, MCP's two bounded workspace dependencies, and no
  other workspace dependency edges.
- Installation smoke tests for both wheels and source archives, with a fresh environment per distribution that installs
  only that artifact and resolves workspace dependencies from its metadata.
- EditorConfig settings aligned with the repository's formatters and file types.

### Changed

- **Breaking:** the SDK classes `OpenDart`, `OpenDartSettings`, and `OpenDartError` are renamed `OpenDART`,
  `OpenDARTSettings`, and `OpenDARTError`.
