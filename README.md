# OpenDART

Python SDK, analysis library, and MCP server for Korean corporate disclosures through the
**English OpenDART API** operated by Korea's Financial Supervisory Service.

Official OpenDART API websites: [English](https://engopendart.fss.or.kr/) and
[Korean](https://opendart.fss.or.kr/).

This is a uv workspace with three independently installable packages and one `uv.lock`:

| Package | Python import | Contents | Depends on |
| --- | --- | --- | --- |
| [`packages/sdk`](packages/sdk) (`opendart-sdk`) | `opendart` | Async client for all 85 documented services, returning the API's raw models and ZIP bytes | httpx2, Pydantic, pydantic-settings, defusedxml |
| [`packages/analysis`](packages/analysis) (`opendart-analysis`) | `opendart_analysis` | Filing parsing, company resolution, the service catalog, and analysis workflows (financials, events, filings, ownership, capital, debt, dividends, governance, and calendars) over caller-supplied data | AnyIO, defusedxml, Pydantic |
| [`packages/mcp`](packages/mcp) (`opendart-mcp`) | `opendart_mcp` | Local Streamable HTTP server with 13 read-only analyst tools, resources, prompts, and MCP Apps | `opendart-sdk`, `opendart-analysis`, FastMCP, MCP, OpenTelemetry API |

The SDK and analysis are independent: neither imports the other or MCP, and
[`importlinter.toml`](importlinter.toml) enforces it. The three packages share one version and are released together.

The SDK supports the 82 JSON services and three ZIP downloads in the
[published API reference](https://orestxherija.github.io/opendart/); its source
and generation guide are in [`api_reference/`](api_reference/README.md). XML
alternatives to JSON are not exposed.
The Korean-language API is a separate service and is not supported by this SDK.

## Table of contents

- [Choose a package](#choose-a-package)
- [Get an API key](#get-an-api-key)
- [Get started](#get-started)
- [MCP container](#mcp-container)
- [Develop](#develop)
- [Precedent implementations](#precedent-implementations)

## Choose a package

Install only what you need:

| You want to | Install | Guide |
| --- | --- | --- |
| Call the OpenDART API and work with its raw responses | `opendart-sdk` | [SDK guide](packages/sdk/README.md) |
| Parse filings, resolve companies, or analyze data you already have, without the SDK | `opendart-analysis` | [Analysis guide](packages/analysis/README.md) |
| Download with the SDK, then analyze the results in Python | `opendart-sdk` and `opendart-analysis`, at the same version | [Data access recipe](packages/analysis/docs/data-access.md) |
| Give an MCP client tools for Korean filings | `opendart-mcp`, which installs both libraries | [MCP guide](packages/mcp/README.md) |

The packages are not yet published to a package index. From a checkout, `uv sync --locked --package <name>` installs
one package with its dependencies; repeat `--package` to combine them, or use `--all-packages` for the whole
workspace. Outside uv, install from the repository root with pip, listing every workspace package the choice needs so
that pip does not look for them on PyPI, where an unrelated project owns the name `opendart-mcp`:

```sh
python -m pip install ./packages/sdk                                      # SDK only
python -m pip install ./packages/analysis                                 # analysis only
python -m pip install ./packages/sdk ./packages/analysis                  # SDK and analysis
python -m pip install ./packages/sdk ./packages/analysis ./packages/mcp   # MCP server
```

Wheels built with `uv build --all-packages` install the same way: list their paths in `dist/` instead of the
package directories. Each choice is tested in a fresh environment from both wheels and source archives; see the
[release guide](docs/RELEASING.md).

Start with these guides:

- [Raw SDK access](packages/sdk/README.md#use-the-client): the client, settings, downloads, and errors.
- [Standalone filing parsing](packages/analysis/docs/documents.md): read a filing archive into an outline, sections,
  tables, and search results, with or without the SDK.
- [Company resolution](packages/analysis/docs/directory.md): parse the corporation-code directory and resolve names
  and codes to structured outcomes.
- [Analysis workflows](packages/analysis/docs/data-access.md): bind workflows to the SDK or any data source, then use
  [periodic reports](packages/analysis/docs/reports.md), [financial statements](packages/analysis/docs/financials.md),
  [corporate events](packages/analysis/docs/events.md), and the other capabilities in the
  [analysis guide](packages/analysis/README.md#guides).
- [Analysis contracts](packages/analysis/docs/contracts.md): units, missing data, provenance, ambiguity, task
  ownership, configuration, and exceptions.

## Get an API key

OpenDART calls API keys **authentication keys**. Request one through the English
OpenDART site used by this SDK:

1. Open [Request an Authentication Key](https://engopendart.fss.or.kr/uss/umt/EgovMberInsertView.do).
   This form also creates your OpenDART account.
2. Accept the required terms and personal information consent, choose **Individual**
   or **Corporation**, and enter your email, password, API usage environment, and
   intended use. Corporate applications also require company details and supporting
   documentation listed on the form.
3. Submit the registration. The application page states that individual keys are
   issued immediately; corporate keys require approval, typically 1–2 business days.
   The application result is sent by email.
4. Sign in with your registered email and password, then open
   [Authentication Key Management](https://engopendart.fss.or.kr/mng/userApiKeyListView.do)
   to retrieve your key. Use the issued 40-character value for
   `OPENDART_API__API_KEY` in the commands below.

## Get started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
uv sync --locked --all-packages
export OPENDART_API__API_KEY='your-issued-40-character-key'
uv run --package opendart-sdk python
```

```python
import asyncio
from opendart import OpenDART


async def main():
    async with OpenDART() as client:
        company = await client.disclosures.company(corporation_code="00126380")
        print(company.corporation_name)

        page = await client.disclosures.search(
            corporation_code="00126380",
            filing_start_date="20250101",
            filing_end_date="20250331",
            page_number=1,
            page_size=100,
        )
        for filing in page.list or []:
            print(filing.filing_number, filing.report_title)


asyncio.run(main())
```

The client reads environment variables when constructed. The SDK loads a `.env`
file only when explicitly requested with `Settings(_env_file=".env")`; alternatively,
direnv can export its values into your shell as described below. The SDK never
loads credentials at import time. See the [SDK guide](packages/sdk/README.md) for
explicit settings, downloads, and error handling.

## MCP container

Building the container requires Docker with BuildKit and Compose v2, a
[Docker account](https://app.docker.com/signup), and a Docker personal access token
with read access to [Docker Hardened Images](https://docs.docker.com/dhi/how-to/use/).
Authenticate first; paste the PAT at the password prompt:

```sh
docker login dhi.io --username YOUR_DOCKER_ID
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
```

This starts a Streamable HTTP MCP server at `http://127.0.0.1:8000/mcp`, published
only on localhost. Without an API key it still lists every component, and tool calls
explain how to configure one.
The root [`.mcp.json`](.mcp.json) configures that connection for compatible MCP
clients. Start the server before connecting. To run without Docker,
use `uv run --no-sync opendart-mcp` after syncing the workspace.
See the [MCP guide](packages/mcp/README.md#docker) for PAT creation, smoke tests,
host configuration, and the manual GHCR publishing workflow. Repository
maintainers must also [configure DHI secrets for CI and Renovate](packages/mcp/docs/CONTAINER.md#dhi-credentials).

## Develop

Python 3.14+ is supported; `.python-version` selects Python 3.14 for local development.
The HTTP and settings implementations follow the repository's `python-http` and
`python-settings` plugin conventions, using httpx2 and Pydantic.
The root [`.editorconfig`](.editorconfig) makes every standard editor property
explicit and matches the repository's file formats and formatter settings.

`uv sync` installs the locked [Just](https://just.systems/) task runner into `.venv`; run it
through the activated environment, direnv as described below, or `uv run just`. Run `just`
to list commands, `just sync` to install the Python workspace and offline test
dependencies, and `just reference sync` to install documentation dependencies.
Use `just sdk test`, `just analysis test`, `just mcp run`, or `just reference build` from the root, or
run `just test` inside a package. `just check` runs repository quality checks and
all offline component checks. `just quality` runs repository checks, including
actionlint and ShellCheck. `just audit` runs Zizmor against workflows and shared
actions and checks all locked Python dependencies against current advisories;
`just ci plan` previews which CI checks the current changes select;
`just secrets` scans all local Git history, and `just links` audits external
documentation links. Taplo and Markdownlint require Node.js 22+ and npm; their
pinned CLIs are installed on first use, and TOML schema validation can fetch
remote schemas.

Pip-audit runs before pushes that change `uv.lock` and exports every workspace
package, dependency group, and optional extra from the lockfile. It audits registry packages without
installing them; local workspace packages are omitted while their dependencies
remain covered. Zizmor runs before commits and merges when GitHub YAML or its
configuration changes, scanning all workflow and action definitions together.

The `api_reference/` directory contains API documents and source data. Reference
tooling, dependency manifests, and the Just module live in `scripts/api_reference/`;
the contract test harness lives in `tests/contracts/`.

```sh
uv sync --locked --all-packages --group contracts
uv run --no-sync pytest
uv run --no-sync pyrefly check
uv run --no-sync ruff check packages scripts tests
uv run --no-sync ruff format --check packages scripts tests
uv run --no-sync python scripts/generate_sdk.py --check
uv run --no-sync python scripts/api_reference/check.py
uv build --package opendart-sdk
uv build --package opendart-analysis
uv build --package opendart-mcp
uv run --no-sync lint-imports --config importlinter.toml
```

[`pytest.toml`](pytest.toml) configures all four offline suites with strict
configuration and marker checks, randomized order, up to eight parallel workers,
timeouts, blocked network sockets, and HTML reports. The existing AnyIO tests use
their explicit markers. Run `uv run --no-sync pytest -n 0` for a serial run.
[`pyrefly.toml`](pyrefly.toml) applies strict type checking to every package's source
tree, including generated SDK code. [`importlinter.toml`](importlinter.toml) keeps analysis and
the SDK independent: neither imports the other, MCP, or server frameworks, including in
annotations. `just boundaries` checks it against the synced workspace, before each commit
that changes package sources, and in the MCP CI job.

After syncing, run `uv run --no-sync prek install` to install the configured Git
hooks. Commitizen validates new commit messages at the `commit-msg` stage using
Conventional Commits, such as `fix(sdk): handle an empty response`.
Pre-commit hooks are quick and offline: they normalize text and JSON, check file
integrity and syntax, scan staged changes for secrets, audit workflow security, and
check Ruff, Markdown, YAML, TOML formatting, spelling, and the changed files' lengths.
Pyrefly type-checks every package when a commit changes package sources or configuration.
Direct commits to `main` are blocked locally.
Slower checks run before pushes, and only when the pushed commits change their
inputs: Hadolint for the Dockerfile, Taplo schema validation for TOML, Lychee for
Markdown links, pip-audit for `uv.lock`, and the SDK, analysis, MCP, and offline contract
tests for each suite's sources, tests, contract files, and shared test configuration.
Run every pre-push hook manually with `uv run --no-sync prek run --all-files --stage pre-push`.
Python hooks use the installed environment without syncing it. Taplo, Markdownlint,
Lychee, and Betterleaks install pinned tools on first use. Betterleaks verifies
download checksums and always redacts findings in the configured commands.
`just sdk test`,
`just analysis test`, `just mcp test`, `just reference test`, and CI use the same test hooks.
Their HTML reports are written to `.cache/pytest/`, with separate SDK, analysis, and MCP
coverage data and XML reports in `.cache/coverage/`. Branch coverage is configured in the
[SDK `.coveragerc.toml`](packages/sdk/.coveragerc.toml),
[analysis `.coveragerc.toml`](packages/analysis/.coveragerc.toml), and
[MCP `.coveragerc.toml`](packages/mcp/.coveragerc.toml). The package workflows upload
those XML reports to Codecov with separate `sdk`, `analysis`, and `mcp` flags, configured in
[`codecov.yml`](codecov.yml).

The quality configs exclude generated API/SDK files where appropriate and the
vendored convention plugins. Loq caps handwritten files at 500 lines, with explicit
adoption limits for three existing larger files. Pull requests run the same
built-in, Ruff, Markdown, YAML, TOML, spelling, and file-length checks
across the repository through [quality CI](.github/workflows/check-quality.yml),
and scan the full fetched Git history with Betterleaks, including secrets removed in
later commits. Zizmor audits workflows and pip-audit checks locked Python
dependencies when those files change; both also run weekly and manually. External
links are audited weekly or manually, separately from the required PR checks.
Building and smoke-testing the distributions and the MCP image run when their
inputs change, except on draft pull requests; see [GitHub Actions](.github/README.md).
The local branch guard is excluded
from CI, which uses detached checkouts and runs after merges to `main`.

Python dependency resolution uses a 48-hour cooldown to match Safe Chain's CI policy.
Run `uv lock` after changing dependencies and commit the updated `uv.lock`.

`just release-check` verifies coordinated package versions and the release tooling.
`just release-build` also builds wheels and source archives, checks their metadata,
and smoke-tests isolated installations. See the [release guide](docs/RELEASING.md)
for version updates, the [changelog](CHANGELOG.md), and artifact preparation.
Renovate waits the same two days before proposing any dependency update.

To load local environment variables and activate `.venv` automatically when entering
the project, install [direnv](https://direnv.net/docs/installation.html) and
[enable its shell hook](https://direnv.net/docs/hook.html). For zsh, add
`eval "$(direnv hook zsh)"` to `~/.zshrc` and restart your shell.

If `.env` does not exist, copy `.env.example` to `.env`, then set
`OPENDART_API__API_KEY` to your issued key. Run `direnv allow` from the project root.
The checked-in `.envrc` loads `.env` when present and activates the existing `.venv`
created by `uv sync --locked --all-packages`. Run that sync command first on a new
checkout; dependency installation stays explicit. `.env` and direnv's `.direnv/`
state directory are ignored by Git.

Endpoint methods, request models, and response models are generated from the
checked-in OpenAPI files. Change the reference's builder or source snapshot,
regenerate the reference, then regenerate the SDK:

```sh
uv run python scripts/api_reference/build.py
uv run python scripts/generate_sdk.py
```

Generation and SDK tests run offline against synthetic examples and mock transports.
Separate [Schemathesis contract checks](api_reference/CONTRACT_TESTING.md) audit
live JSON, XML, and ZIP responses. After OpenAPI changes reach the default branch,
CI checks only affected operations; its `OPENDART_API_KEY` Actions secret is required.
The reference records the findings and remaining uncertainty about unsampled data.
The SDK preserves financial strings and unknown fields; optional response fields
are represented by `None` when missing or null. API status `013` raises `NoDataError`.
Pagination is explicit: request each page using `page_number` and inspect `total_page`.

## Precedent implementations

The following projects by [hypn4](https://github.com/hypn4) are precedent
implementations in the OpenDART ecosystem:

- [opendart-fss-python](https://github.com/hypn4/opendart-fss-python): a Python SDK
  for the OpenDART API.
- [opendart-fss-mcp](https://github.com/hypn4/opendart-fss-mcp): an MCP server for
  Korea's DART/FSS corporate disclosures.
