# OpenDART

Python SDK and MCP server for Korean corporate disclosures through the
**English OpenDART API** operated by Korea's Financial Supervisory Service.

This is a uv workspace with independently installable packages and one `uv.lock`:

| Package | Python import | Status |
| --- | --- | --- |
| [`packages/sdk`](packages/sdk) (`opendart-sdk`) | `opendart` | Async client for all 85 documented services |
| [`packages/mcp`](packages/mcp) (`opendart-mcp`) | `opendart_mcp` | Stdio server with a `ping` tool for deployment tests |

The SDK supports the 82 JSON services and three ZIP downloads in the existing
[API reference](api_reference/README.md). XML alternatives to JSON are not exposed.
The Korean-language API is a separate service and is not supported by this SDK.

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
        company = await client.disclosures.company(corp_code="00126380")
        print(company.corp_name)

        page = await client.disclosures.search(
            corp_code="00126380", bgn_de="20250101", end_de="20250331",
            page_no=1, page_count=100,
        )
        for filing in page.list or []:
            print(filing.rcept_no, filing.report_nm)


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
docker compose -f packages/mcp/docker-compose.yml run --rm --no-deps -T mcp
```

This starts a stdio MCP server with a `ping` tool that returns `pong`, without an
API key. See the [MCP guide](packages/mcp/README.md) for smoke tests, host
configuration, and the manual GHCR publishing workflow.

## Develop

Python 3.11+ is supported; `.python-version` selects Python 3.14 for local development.
The HTTP and settings implementations follow the repository's `python-http` and
`python-settings` plugin conventions, using httpx2 and Pydantic.

```sh
uv sync --locked --all-packages
uv run pytest
uv run mypy
uv run ruff check packages scripts
uv run ruff format --check packages scripts
uv run python scripts/generate_sdk.py --check
uv run python api_reference/scripts/check.py
uv build --package opendart-sdk
uv build --package opendart-mcp
```

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
uv run python api_reference/scripts/build.py
uv run python scripts/generate_sdk.py
```

Generation and tests run offline against synthetic examples and mock transports.
No authenticated upstream success calls have been made; the reference documents
remaining uncertainty about actual response scalar types and missing fields.
The SDK preserves financial strings and unknown fields; optional response fields
are represented by `None` when missing or null. API status `013` raises `NoDataError`.
Pagination is explicit: request each page using `page_no` and inspect `total_page`.
