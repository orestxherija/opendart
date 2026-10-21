# OpenDART

Python SDK and MCP server for Korean corporate disclosures through the
**English OpenDART API** operated by Korea's Financial Supervisory Service.

Official OpenDART API websites: [English](https://engopendart.fss.or.kr/) and
[Korean](https://opendart.fss.or.kr/).

This is a uv workspace with independently installable packages and one `uv.lock`:

| Package | Python import | Status |
| --- | --- | --- |
| [`packages/sdk`](packages/sdk) (`opendart-sdk`) | `opendart` | Async client for all 85 documented services |
| [`packages/mcp`](packages/mcp) (`opendart-mcp`) | `opendart_mcp` | Local HTTP server with a `ping` tool for deployment tests |

The SDK supports the 82 JSON services and three ZIP downloads in the existing
[API reference](api_reference/README.md). XML alternatives to JSON are not exposed.
The Korean-language API is a separate service and is not supported by this SDK.

## Table of contents

- [Get an API key](#get-an-api-key)
- [Get started](#get-started)
- [MCP container](#mcp-container)
- [Develop](#develop)
- [Precedent implementations](#precedent-implementations)

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
from opendart import OpenDart


async def main():
    async with OpenDart() as client:
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

```sh
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
```

This starts a Streamable HTTP MCP server at `http://127.0.0.1:8000/mcp`, published
only on localhost, with a `ping` tool that returns `pong` without an API key.
The root [`.mcp.json`](.mcp.json) configures that connection for compatible MCP
clients. Start the server before connecting. To run without Docker,
use `uv run --no-sync opendart-mcp` after syncing the workspace.
See the [MCP guide](packages/mcp/README.md) for smoke tests, host
configuration, and the manual GHCR publishing workflow.

## Develop

Python 3.14+ is supported; `.python-version` selects Python 3.14 for local development.
The HTTP and settings implementations follow the repository's `python-http` and
`python-settings` plugin conventions, using httpx2 and Pydantic.

For task shortcuts, install [Just](https://just.systems/) 1.33 or newer. Run `just`
to list commands, `just sync` to install the Python workspace and offline test
dependencies, and `just reference sync` to install documentation dependencies.
Use `just sdk test`, `just mcp run`, or `just reference build` from the root, or
run `just test` inside a package. `just check` runs all component checks offline.

```sh
uv sync --locked --all-packages
uv run pytest
uv run mypy
uv run ruff check packages scripts tests
uv run ruff format --check packages scripts tests
uv run python scripts/generate_sdk.py --check
uv run python scripts/api_reference/check.py
uv build --package opendart-sdk
uv build --package opendart-mcp
```

Python dependency resolution uses a 48-hour cooldown to match Safe Chain's CI policy.
Run `uv lock` after changing dependencies and commit the updated `uv.lock`.
Dependabot uses the same cooldown for Python and npm updates.

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
