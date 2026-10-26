# CI

GitHub Actions workflows that check changes, publish the MCP image, and audit the repository on a schedule.

## Table of contents

- [Workflows](#workflows)
- [Change selection](#change-selection)
- [Run checks locally](#run-checks-locally)
- [Secrets](#secrets)
- [Conventions](#conventions)

## Workflows

| Workflow | Trigger | Runs |
| --- | --- | --- |
| [CI](ci.yml) | Pull request | File, style, and secret checks always; audit, release, SDK, analysis, MCP, image, and reference checks when their inputs change |
| [CI](ci.yml) | Push to `main` | SDK, analysis, MCP, and reference checks for Codecov and Pages; publishes the image and tests live API contracts when their inputs change |
| [Release MCP image](release-image.yml) | Tag `vX.Y.Z` | Verifies, rescans, and tags the commit's published image |
| [Scheduled audits](scheduled-audits.yml) | Monday 08:23 UTC | Zizmor, pip-audit, and documentation links |
| [Scheduled image scan](scheduled-image-scan.yml) | Daily 05:23 UTC | Verifies and scans the published `main` image |

The `check-*.yml` and `test-live-contracts.yml` workflows have no triggers of their own; CI and the scheduled audits
call them. CI also calls `publish-mcp-image.yml`. Manual runs: **CI** takes one input per check and never publishes,
**Publish MCP image** republishes `main`, **Release MCP image** retries a tag, and both scheduled workflows run on demand.

## Change selection

The first CI job compares the change with its base, applies the filters in
[`scripts/ci/ci-paths.toml`](../../scripts/ci/ci-paths.toml), and calls only the check workflows whose inputs changed.
The required **CI checks** job passes when every selected check passes. Draft pull requests skip the image,
distribution, and MCP conformance checks until they are marked ready. Run `just ci plan` to preview the selection for
local changes.

## Run checks locally

Run these after `just sync`. Markdownlint, Taplo, and the Renovate config validator also need Node.js and npm.

- `just check`: repository quality checks and every component's offline suite.
- `just quality`: file integrity, style, shell scripts, workflows, spelling, and file lengths.
- `just audit`: Zizmor on workflows and actions, and pip-audit on the locked dependencies.
- `just secrets`: Betterleaks over all local Git history, with redacted output.
- `just links`: Lychee over documentation links, including external sites.
- `just ci plan`: the CI checks that the current changes select, compared with `origin/main` by default.
- `just ci test`: tests for change selection and the tool pins that must match.
- `uv run --no-sync prek install`: installs the Git hooks. Pre-commit hooks are fast and offline; Commitizen checks
  commit messages against Conventional Commits. Pre-push hooks (Hadolint, Taplo schema validation, Lychee, pip-audit,
  and the test suites) are slower and run only when the pushed commits change their inputs.
- `uv run --no-sync prek run --all-files --stage pre-push`: runs every pre-push hook regardless of what changed.

## Secrets

| Secret | Used by |
| --- | --- |
| `CODECOV_TOKEN` | SDK, analysis, and MCP checks, to upload coverage to Codecov |
| `DHI_USERNAME`, `DHI_TOKEN` | MCP image check and image publishing, to pull Docker Hardened Images from `dhi.io` and authenticate Docker Scout's signature checks |
| `OPENDART_API_KEY` | Live API contract tests on pushes to `main` |

- `DHI_USERNAME` is a Docker ID and `DHI_TOKEN` a Docker personal access token with read access to public
  repositories. Add them under **Settings → Secrets and variables → Actions**, or run `gh secret set DHI_USERNAME` and
  `gh secret set DHI_TOKEN`, which prompt for each value.
- Renovate needs its own copy to look up DHI tags and digests: add both under **Credentials** in this repository's
  settings in the [Mend developer portal](https://developer.mend.io/). Renovate stops updating the repository if a
  credential that `renovate.json` references is missing.
- When the token expires or is rotated, update it in GitHub and in the Mend portal.
- GitHub gives no secrets to pull requests from forks. For a fork change to the image's inputs, a maintainer reviews
  it and runs it from a branch in this repository. Keep workflows on `pull_request`; never expose secrets with
  `pull_request_target`.

## Conventions

- Light jobs run on `ubuntu-slim`; Docker, parallel tests, and type checks use `ubuntu-latest`.
- The [`setup`](../actions/setup/action.yml) composite action installs the pinned uv and Python and, when a job asks,
  Node.js, Safe Chain, and the locked dependencies. The other actions in `.github/actions/` generate image labels,
  sign and verify images, and scan them with Trivy.
- Third-party actions are pinned to full commit SHAs, with the version in a trailing comment.
- Steps call the same `just` recipes as local development; other CI logic lives in `scripts/ci/` (change selection
  and tool bootstrap), `scripts/mcp/` (container checks), and `scripts/release/` (image release).
- [Renovate](../../renovate.json) runs early on Mondays (UTC) and proposes only releases at least two days old. Minor
  updates arrive in one grouped pull request; patch and digest updates merge themselves after CI passes.
