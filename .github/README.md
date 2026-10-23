# GitHub Actions

[CI](workflows/ci.yml) runs on pull requests and pushes to `main`. It detects the
changed files once, then calls the relevant reusable workflows. Feature branch
pushes are checked through their pull requests, avoiding duplicate runs. The path
rules live in [ci-paths.yml](ci-paths.yml). Checks are grouped by cost:

- **Every pull request change:** repository quality, which covers file integrity,
  Ruff, Markdown, YAML, TOML, spelling, and file lengths across the repository,
  and a Betterleaks scan of the fetched Git history.
- **When their inputs change:** workflow and dependency audits, release metadata,
  and the SDK, MCP, and API reference checks.
- **Expensive, when their inputs change:** building and smoke-testing both
  packages' distributions, and building, exercising, and scanning the MCP image.
  These gate pull requests too, because they catch breakage the change itself
  causes. Draft pull requests skip them; marking a draft ready runs them.
- **After merges to `main` or on a schedule:** live API contract tests, Pages
  deployment, and the daily and weekly security audits, whose results depend on
  external services or newly published advisories rather than on the change.

Pull requests need not be up to date with `main` before merging, so the push to
`main` reruns the SDK, MCP, and API reference checks for its changes. They test
how merged Python changes combine, upload the coverage baseline that Codecov
compares pull requests against, and build the site for Pages. The push skips the
rest, which the pull request already ran: file and secret checks examine the
same content, audits catch new advisories on their schedule, and publishing and
the release steps recheck the image and distributions before anything ships.

Publishing is the one expensive job that runs on `main`. When a push changes
the image's `container` inputs and **CI checks** passes, the **Publish MCP image**
job calls [MCP container](workflows/mcp-container.yml), which tests, scans, signs,
and promotes the image to `main` and `sha-<full-commit>` in GHCR. Pushing a
`vX.Y.Z` release tag promotes the tagged commit's signed digest. See
[Publish to GHCR](../packages/mcp/docs/CONTAINER.md#publish-to-ghcr).

| Changed files | Pull request checks |
| --- | --- |
| MCP package outside `docs/`, `scripts/check_mcp*.py`, or Hadolint config | MCP |
| SDK source, package metadata, or package README | SDK and MCP |
| SDK tests or generator | SDK |
| Shared Codecov or Pyrefly config | SDK and MCP |
| API contract, source catalog, or reference generator | SDK and API reference |
| Reference presentation, npm dependencies, validation script, or `tests/contracts/` | API reference |
| Release versions, helpers, or their tests | Release |
| Ruff or pytest config | SDK, MCP, API reference, and release |
| Prek config | SDK, MCP, API reference, and audits |
| Workflows, shared actions, Dependabot, Zizmor config, pip-audit script, or `uv.lock` | Audits, plus any component listed for that file |
| Root project, uv config or lockfile, Python version, CI routing, or Safe Chain action | SDK, MCP, API reference, and release |
| Component workflow | Its component |
| Documentation, including package `docs/` and `api_reference/*.md` | Repository quality only |

The expensive checks are selected by their own inputs:

- **Distributions:** changes to either package outside its tests and docs, release
  versions or helpers, the release workflow, or shared tooling.
- **MCP image:** changes to the image's inputs (the Dockerfile, `.dockerignore`,
  manifests, lockfile, and SDK and MCP sources), Compose files, container checks
  and their actions, the image workflow, or shared tooling. Within the image check,
  DHI base verification runs only when the Dockerfile or its verification changes,
  and the vulnerability scan only when the Dockerfile, `.dockerignore`, `uv.lock`,
  or the scan changes; the secret scan always runs. Package source does not change
  the image's vulnerabilities, and the daily published-image scan catches new
  advisories.

MCP depends on the installed SDK. Reference contracts feed SDK generation and
contract tests; regenerated SDK source also triggers MCP checks. SDK-only changes
do not rebuild the reference. Ruff in repository quality covers Python examples in
documentation that component checks skip.

The API reference's npm and standalone Python manifests, Redocly configuration,
and task recipes live with its tools in `scripts/api_reference/`. The Pages build
and Dependabot use that directory; `api_reference/` holds API documents and data.

- [Repository quality](workflows/quality.yml): run the built-in Prek file checks,
  repository-wide Ruff lint and format checks, and the `markdownlint-cli2`,
  `yamllint`, `taplo-format`, `typos`, and `loq` hooks across tracked files, then
  validate TOML schemas with `taplo-lint`. The local `no-commit-to-branch` policy
  is excluded because CI also runs on `main` and detached merge commits.
  Betterleaks runs in a separate required job against all fetched Git history,
  including secrets introduced and removed within a PR or push. Its pinned
  download is checksum verified, findings are redacted, and no secret reports are
  uploaded. These checks run for every PR, including changes that skip all
  component workflows. A separate security job runs Zizmor against every
  workflow, shared action, and Dependabot configuration, then pip-audit against
  all registry packages in the workspace lockfile, including every dependency
  group and optional extra. The audit exports the lockfile without installing
  the audited packages. Zizmor uses the read-only GitHub token for online checks.
  CI runs this job when workflows, shared actions, Dependabot, Prek or Zizmor
  configuration, the pip-audit script, or `uv.lock` change. Zizmor, pip-audit,
  Betterleaks, and Lychee also run each Monday at 08:23 UTC and on manual quality
  runs, which catches advisories published for unchanged dependencies; Lychee
  retains a seven-day link report. External site failures do not block pull
  requests.
- [Release artifacts](workflows/release.yml): verify the SDK/MCP/Commitizen
  version agreement and test the release helpers, using the locked release
  dependency group. When either package or the release tooling changes, and on
  manual runs, also build both wheels and source archives, check their metadata
  and readmes, and smoke-test isolated installations. The isolated installs catch
  runtime imports that only the development environment provides.
- [SDK checks](workflows/sdk.yml): lint, format, type-check with Pyrefly,
  verify generated code, run SDK tests, upload coverage, and build the SDK package
  on Python 3.14.
- [MCP checks](workflows/mcp.yml): Hadolint, Python lint, format, Pyrefly
  type checks, test listener settings, smoke-test the local HTTP server, build the
  MCP package, and validate Compose on Python 3.14.
- [MCP image checks](workflows/mcp-image.yml): when the image's inputs change, and
  on manual runs, build the container with cached layers after verifying the DHI
  base attestations, exercise its restricted runtime and synthetic file secret,
  reject hostile HTTP headers, and scan vulnerabilities and secrets. Retain full
  vulnerability findings, including unfixed CVEs, for 30 days. Publishing always
  repeats every check on the exact candidate before promoting it.
- [API reference Pages](workflows/pages.yml): validate the reference, lint OpenAPI,
  build HTML, and upload the Pages artifact. Successful builds on `main` deploy
  to GitHub Pages; pull requests only build.
- [MCP container](workflows/mcp-container.yml): called by CI after a passing
  `main` push that changes the image's inputs or this workflow, or run manually on
  `main`. Pull requests that change only this workflow skip the image check, which
  would not exercise it. Lint,
  verify DHI attestations, build and push one untagged candidate by digest, test
  and scan that digest, sign and verify it with GitHub OIDC/Cosign, then promote
  the same index to `sha-<full-commit>` and `main`. SBOM/provenance are preserved.
  Runs are serialized, and `main` never moves to an older commit. A pushed
  `vX.Y.Z` tag, matching the package version on a `main` commit, verifies and
  rescans that commit's published digest and adds the release tag without
  rebuilding. Failed candidates never receive tags.
- [MCP published image security](workflows/mcp-security.yml): daily or manual
  signature verification and vulnerability/secret scans of the published `main`
  digest, with a 30-day full vulnerability report. A manual digest input audits
  an older default-branch build. Publish a signed default-branch build first.
- [Live API contracts](workflows/contracts.yml): after OpenAPI changes are pushed
  to `main`, the default branch, use Schemathesis to check only added or changed
  operations, including consumers of changed shared schemas. Uses the
  `OPENDART_API_KEY` Actions secret and uploads sanitized findings even on failure.
  A manual run on the default branch audits all operations. See the
  [contract testing guide](../api_reference/CONTRACT_TESTING.md).

Each component workflow supports **Run workflow** to force its checks. Running
**CI** manually forces repository quality, audits, release metadata, and every
component, including the distribution build and every MCP image check, also on
draft pull request branches. A manual **Repository
quality** run also checks documentation links by default; clear **check-links**
or **audit** to skip those checks. A manual **Release artifacts** run builds the
distributions unless **build** is cleared. Manual API reference runs on `main`
also deploy the site. A manual **MCP container** run republishes the tip of
`main`; a manual **CI** run never publishes.
Live contract tests are separate from the PR gate: their selector and validators
in `tests/contracts/` are tested offline by API reference CI, while authenticated
requests run only after a default-branch merge/push or an explicit full audit.

The three offline test jobs run the same pre-push hooks as local development,
using the root `pytest.toml`. Tests use randomized order, up to eight workers,
timeouts, and disabled network sockets. Each job uploads its HTML test report
(also when tests fail) with seven-day retention. The
[SDK coverage config](../packages/sdk/.coveragerc.toml) and
[MCP coverage config](../packages/mcp/.coveragerc.toml) select each package's source
tree and keep coverage data and XML reports separate under `.cache/coverage/`.
Their uploads use the component flags in [codecov.yml](../codecov.yml); changes to
that shared file trigger both package workflows. Pyrefly uses the shared strict
`pyrefly.toml`, with each package workflow checking its own source tree.

The active default-branch ruleset requires **CI checks** from GitHub Actions
before merging. It runs even when all component jobs are skipped, fails if change
detection fails, and requires repository quality and each selected component to
succeed, including the component's Ruff lint and format checks. GitHub does not
merge draft pull requests, so the expensive checks they skip always run before a
merge.

All workflows that install Python or npm dependencies use the existing
[Aikido Safe Chain action](actions/setup-safe-chain/action.yml), pinned to a
checksum-verified release. Each package manager is verified before installing
dependencies. Aikido runs within the relevant component and quality jobs, so
skipped components do not install dependencies or run Safe Chain. Quality jobs
install only the hook and quality dependency groups; the release job installs the
workspace and development groups, including release tools. Link audits need only
the hook runner.

Light jobs run on `ubuntu-slim`: change detection, the **CI checks** aggregator,
repository quality, audits, secret and link scans, and Pages deployment. This
single-CPU runner costs a third of the standard Linux rate, caps jobs at 15
minutes, and has no Docker. Jobs that use Docker or run parallel tests and type
checkers stay on `ubuntu-latest`; the MCP image targets `linux/amd64`, so its
build also stays on x64.

## Docker Hardened Images credentials

The MCP image check and publishing workflows pull their Python base images from
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

[CI](workflows/ci.yml) passes these two secrets only to the reusable
[MCP image checks](workflows/mcp-image.yml) workflow, which runs only when the
image's inputs change, or on manual runs, and to [MCP container](workflows/mcp-container.yml)
when it publishes from `main`; only that publish job receives `packages: write` and
`id-token: write`. The image check and publishing workflows authenticate
before building and log out afterward. Missing credentials fail the build with a setup
message; container tests and Trivy remain required. GHCR publishing continues
to use `GITHUB_TOKEN` separately.

DHI signature checks use the free Docker Scout CLI and Docker's public key.
The verification step passes the same DHI username and PAT to Scout's Docker Hub
authentication through `DOCKER_SCOUT_HUB_USER` and `DOCKER_SCOUT_HUB_PASSWORD`;
logging in to `dhi.io` alone does not authenticate Scout.
The public Sigstore service signs our image using the publishing workflow's
short-lived GitHub OIDC identity (`id-token: write`); no extra subscription or
signing secret is required. This publishes the workflow identity in the public
transparency log. The daily scan only needs `packages: read`, not DHI credentials.
Build/scanning/signing still consume the repository's normal Actions and GHCR
usage allowance. See the [image verification instructions](../packages/mcp/docs/CONTAINER.md#verify-signatures).

GitHub does not provide repository secrets to pull requests from forks. For a
fork change to the image's inputs, a maintainer must review it and run the PR
from a branch in this repository to complete the required image checks. Keep the
workflows on `pull_request`; do not expose registry credentials with
`pull_request_target`.

After adding the secrets, rerun the failed jobs.
When the PAT expires or is rotated, update it in both GitHub secret stores and
run `docker login dhi.io --username YOUR_DOCKER_ID` again on development machines.
