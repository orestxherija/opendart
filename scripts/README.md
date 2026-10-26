# Repository tooling

Scripts grouped by the work they support. Run the `just` recipes from the repository root; package tests stay in
`packages/*/tests/`.

## Table of contents

- [Directories](#directories)
- [Internal helpers](#internal-helpers)

## Directories

| Directory | Responsibility | Entry points |
| --- | --- | --- |
| [`sdk/`](sdk/) | Generate SDK models and resources from the API reference | `just sdk generate`, `just sdk generated` |
| [`analysis/`](analysis/) | Generate the analysis service catalog | `just analysis generate`, `just analysis generated` |
| [`api_reference/`](api_reference/) | Snapshot guides, generate and validate OpenAPI, build Redoc, audit live contracts | [API reference](../api_reference/README.md) |
| [`mcp/`](mcp/) | Check components, HTTP, container restrictions, base images, and protocol conformance | `just mcp components`, `just mcp smoke`, `just mcp conformance` |
| [`release/`](release/) | Check distributions and installs, validate tags, promote image digests | `just release-check`, `just release-build` |
| [`quality/`](quality/) | Run Betterleaks and dependency audits | `just secrets`, `just audit` |
| [`ci/`](ci/) | Select CI checks and test CI behavior | `just ci plan`, `just ci test` |
| [`testing/`](testing/) | Shared synthetic test data and Git fixtures | Imported by tests |

Tests for these tools live beside them, for example in `ci/tests/` and `release/tests/`. Workflows are documented in
the [CI README](../.github/workflows/README.md).

## Internal helpers

These run only inside other tools:

- [`release/smoke_installed.py`](release/smoke_installed.py) runs in each isolated installation created by
  `release/smoke_distributions.py`.
- [`mcp/check_mcp_runtime.py`](mcp/check_mcp_runtime.py) runs inside the container through
  `mcp/check_mcp_container.sh`.
