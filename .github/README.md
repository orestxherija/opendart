# GitHub Actions

[CI](workflows/ci.yml) runs on pull requests and pushes to `main`. It detects the
changed files once, then calls only the relevant reusable workflows. Feature
branch pushes are checked through their pull requests, avoiding duplicate runs.
The path rules live in [ci-paths.yml](ci-paths.yml).

| Changed files | Automatic checks |
| --- | --- |
| MCP package or `scripts/check_mcp.py` | MCP |
| SDK source, package metadata, or package README | SDK and MCP |
| SDK tests, generator, or Codecov config | SDK |
| API contract, source catalog, or reference generator | SDK and API reference |
| Reference presentation, npm dependencies, or validation script | API reference |
| Reference tooling in `scripts/api_reference/` or tests in `tests/contracts/` | API reference; generators also trigger SDK |
| Shared Python config (including Ruff and Prek), lockfile, CI routing, or shared actions | All three |
| Docker build context or Hadolint config | MCP |
| Component workflow | Its component |
| Root README, development editor config, or plugin documentation | No component checks |

MCP depends on the installed SDK. Reference contracts feed SDK generation and
contract tests; regenerated SDK source also triggers MCP checks. SDK-only changes
do not rebuild the reference.

- [SDK checks](workflows/sdk.yml): lint, format, type-check, verify generated code,
  run SDK tests, upload coverage, and build the SDK package on Python 3.14.
- [MCP checks](workflows/mcp.yml): Hadolint, Python lint, format, type-check,
  test listener settings, smoke-test the local HTTP server, and build the MCP
  package on Python 3.14. Build the
  container with cached layers, validate Compose, test its restricted runtime,
  and scan OS/Python packages for fixable high or critical vulnerabilities.
- [API reference Pages](workflows/pages.yml): validate the reference, lint OpenAPI,
  build HTML, and upload the Pages artifact. Successful builds on `main` deploy
  to GitHub Pages; pull requests only build.
- [MCP container](workflows/mcp-container.yml): manually lint, build, test,
  scan, publish to GHCR with commit/run tags and SBOM/provenance attestations,
  and verify the published digest. Default-branch runs also update `test`.
- [Live API contracts](workflows/contracts.yml): after OpenAPI changes reach the
  configured default branch, use Schemathesis to check only added or changed
  operations, including consumers of changed shared schemas. Uses the
  `OPENDART_API_KEY` Actions secret and uploads sanitized findings even on failure.
  A manual run on the default branch audits all operations. See the
  [contract testing guide](../api_reference/CONTRACT_TESTING.md).

Each component workflow supports **Run workflow** to force its checks. Running
**CI** manually forces all three components. Manual API reference runs on `main`
also deploy the site; container publication is always manual.
Live contract tests are separate from the PR gate: their selector and validators
in `tests/contracts/` are tested offline by API reference CI, while authenticated
requests run only after a default-branch merge/push or an explicit full audit.

The active default-branch ruleset requires **CI checks** from GitHub Actions
before merging. It runs even when all component jobs are skipped, fails if change
detection fails, and requires each selected component to succeed, including its
Ruff lint and format checks.

All workflows that install Python or npm dependencies use the existing
[Aikido Safe Chain action](actions/setup-safe-chain/action.yml), pinned to a
checksum-verified release. Each package manager is verified before installing
dependencies. Aikido runs within the relevant component jobs, so skipped
components do not install dependencies or run Safe Chain.
