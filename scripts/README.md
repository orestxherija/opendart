# Repository tooling

Run the `just` recipes from the repository root. Scripts are grouped by the work
they support; package tests remain in `packages/*/tests/`.

| Directory | Responsibility | Normal entry points |
| --- | --- | --- |
| [`sdk/`](sdk/) | Generate SDK models and resources from the API reference | `just sdk generate`, `just sdk generated` |
| [`analysis/`](analysis/) | Generate the analysis service catalog | `just analysis generate`, `just analysis generated` |
| [`api_reference/`](api_reference/) | Snapshot guides, generate and validate OpenAPI, build Redoc, audit live contracts | [Reference workflow](../api_reference/README.md) |
| [`mcp/`](mcp/) | Check components, HTTP, container restrictions, base-image attestations, and protocol conformance | `just mcp components`, `just mcp smoke`, `just mcp conformance`, image workflows |
| [`release/`](release/) | Check distribution metadata and installations, validate release tags, resolve and promote image digests | `just release-check`, `just release-build`, image workflows |
| [`quality/`](quality/) | Run checksum-verified Betterleaks and locked dependency audits | `just secrets`, `just audit`, Git hooks |
| [`ci/`](ci/) | Select CI checks, configure routing, bootstrap Safe Chain, and test CI behavior | `just ci plan`, `just ci test`, workflow setup |
| [`testing/`](testing/) | Share synthetic test data and Git isolation fixtures across suites | Imported by tests |

CI selection code, routing configuration, recipes, and tests live together in
[`ci/`](ci/). GitHub workflows and composite actions stay in [`.github/`](../.github/).
Release and reference tooling tests live in [`release/tests/`](release/tests/) and
[`api_reference/tests/`](api_reference/tests/). Live contract commands live in
[`api_reference/contracts/`](api_reference/contracts/), separate from those tests.

## Occasional tools and internal helpers

- [`scripts/api_reference/snapshot.py`](api_reference/snapshot.py) fetches the
  upstream guides when refreshing the checked-in snapshot. Normal generation and
  validation use the existing snapshot offline.
- [`scripts/api_reference/contracts/selection.py`](api_reference/contracts/selection.py)
  and [`scripts/api_reference/contracts/run.py`](api_reference/contracts/run.py)
  select and audit live operations when API definitions change or on demand.
  Live audits need an API key; offline tests exercise their behavior without one.
- [`scripts/release/smoke_installed.py`](release/smoke_installed.py) is an internal
  probe launched by `scripts/release/smoke_distributions.py` inside each isolated
  installation; it is part of the distribution checks.
- [`scripts/mcp/check_mcp_runtime.py`](mcp/check_mcp_runtime.py) runs inside the
  container through `scripts/mcp/check_mcp_container.sh`; it checks Linux
  runtime restrictions and is part of the image checks.

All retained scripts have documented commands, recipes, hooks, CI, or internal
callers. No abandoned one-off inspection scripts were found.
