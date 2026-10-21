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
  container with cached layers after verifying the DHI base attestations,
  validate Compose, exercise its restricted runtime and synthetic file secret,
  reject hostile HTTP headers, and scan vulnerabilities and secrets. Retain
  full vulnerability findings, including unfixed CVEs, for 30 days.
- [API reference Pages](workflows/pages.yml): validate the reference, lint OpenAPI,
  build HTML, and upload the Pages artifact. Successful builds on `main` deploy
  to GitHub Pages; pull requests only build.
- [MCP container](workflows/mcp-container.yml): manually lint, verify DHI
  attestations, build and push one candidate, test and scan its immutable digest,
  sign and verify it with GitHub OIDC/Cosign, then promote the same index to
  commit/run tags. SBOM/provenance are preserved. Default-branch runs also update
  `test` after verification. Failed candidates never advance these consumer tags.
- [MCP published image security](workflows/mcp-security.yml): daily or manual
  signature verification and vulnerability/secret scans of the published `test`
  digest, with a 30-day full vulnerability report. A manual digest input audits
  an older default-branch build. Publish a signed default-branch build first.
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

## Docker Hardened Images credentials

The MCP check and publishing workflows pull their Python base images from
`dhi.io`. This requires a Docker account and a Docker PAT with read access to
public repositories. Follow the [MCP Docker setup](../packages/mcp/README.md#docker)
to create the account/token and authenticate for local builds.

In this GitHub repository, add the following under **Settings → Secrets and
variables → Actions → New repository secret**:

| Secret | Value |
| --- | --- |
| `DHI_USERNAME` | Your Docker ID (username) |
| `DHI_TOKEN` | Your Docker personal access token with read access |

Add the same two names and values under **Settings → Secrets and variables →
Dependabot**. Dependabot has its own secret store: it needs these credentials
to check DHI versions and digests, and workflows triggered by Dependabot PRs
use Dependabot secrets. See [GitHub's registry credential guide](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/manage-your-dependency-security/configure-access-to-private-registries).

Alternatively, use the GitHub CLI from the repository root. Each command prompts
for the value; enter your Docker ID for `DHI_USERNAME` and your PAT for `DHI_TOKEN`:

```sh
gh secret set DHI_USERNAME
gh secret set DHI_TOKEN
gh secret set DHI_USERNAME --app dependabot
gh secret set DHI_TOKEN --app dependabot
```

[CI](workflows/ci.yml) explicitly passes these two secrets to the reusable
[MCP checks](workflows/mcp.yml) workflow. Both MCP workflows authenticate before
building and log out afterward. Missing credentials fail the build with a setup
message; container tests and Trivy remain required. GHCR publishing continues
to use `GITHUB_TOKEN` separately.

DHI signature checks use the free Docker Scout CLI and Docker's public key.
The public Sigstore service signs our image using the publishing workflow's
short-lived GitHub OIDC identity (`id-token: write`); no extra subscription or
signing secret is required. This publishes the workflow identity in the public
transparency log. The daily scan only needs `packages: read`, not DHI credentials.
Build/scanning/signing still consume the repository's normal Actions and GHCR
usage allowance. See the [image verification instructions](../packages/mcp/README.md#publish-to-ghcr).

GitHub does not provide repository secrets to pull requests from forks. For an
MCP change from a fork, a maintainer must review it and run the PR from a branch
in this repository to complete the required container checks. Keep the workflows
on `pull_request`; do not expose registry credentials with `pull_request_target`.

After adding the secrets and pushing the changes, rerun the failed PR jobs.
When the PAT expires or is rotated, update it in both GitHub secret stores and
run `docker login dhi.io --username YOUR_DOCKER_ID` again on development machines.
