# OpenDART

Python SDK, analysis library, and MCP server for Korean corporate disclosures through the
**English OpenDART API** operated by Korea's Financial Supervisory Service (FSS).
Official OpenDART API websites: [English](https://engopendart.fss.or.kr/) and
[Korean](https://opendart.fss.or.kr/). The Korean site is the same API in Korean; this repository is built and tested
against the English endpoint only.

[![CI](https://github.com/orestxherija/opendart/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/orestxherija/opendart/actions/workflows/ci.yml?query=branch%3Amain)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![code style: Ruff](https://img.shields.io/badge/code%20style-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![type check: Pyrefly](https://img.shields.io/badge/type%20check-pyrefly-blueviolet)](https://pyrefly.org/)

## Table of contents

- [Packages](#packages)
- [Repository layout](#repository-layout)
- [Get started](#get-started)
- [Development](#development)
- [Related projects](#related-projects)

## Packages

This is a uv workspace with three independently installable packages and one `uv.lock`:

| Package | Import | Purpose | Guide |
| --- | --- | --- | --- |
| `opendart-sdk` | `opendart` | Async client for the English OpenDART API, returning its raw models and ZIP bytes | [SDK](packages/sdk/README.md) |
| `opendart-analysis` | `opendart_analysis` | Filing parsing, company resolution, and analysis workflows over caller-supplied data | [Analysis](packages/analysis/README.md) |
| `opendart-mcp` | `opendart_mcp` | Local Streamable HTTP MCP server with read-only analyst tools, also built as a Docker image | [MCP](packages/mcp/README.md) |

The SDK and analysis are independent, so neither imports the other; MCP depends on both. All three packages share
one version and are released together.

## Repository layout

- `packages/`: the three workspace packages, each with its source, tests, `pyproject.toml`, and `justfile`.
- [`api_reference/`](api_reference/README.md): the OpenAPI description of the English OpenDART API that the SDK is
  generated from, published as a [browsable reference](https://orestxherija.github.io/opendart/).
- [`scripts/`](scripts/README.md): code generation, API reference, MCP verification, release, quality, and CI tooling.
- [`.github/`](.github/workflows/README.md): GitHub Actions workflows and composite actions.
- Root files configure the workspace and shared tools: `pyproject.toml` and `uv.toml` (uv), `justfile` (tasks),
  `ruff.toml`, `pyrefly.toml`, `pytest.toml`, `prek.toml` (Git hooks), `cz.toml` (Commitizen), `renovate.json`, and
  smaller linter configs.

## Get started

1. Request an authentication key, OpenDART's term for an API key, with the
   [English OpenDART form](https://engopendart.fss.or.kr/uss/umt/EgovMberInsertView.do), which also creates your
   account. Individual keys are issued immediately; corporate keys need approval, typically 1–2 business days.
2. Sign in and copy the 40-character key from
   [Authentication Key Management](https://engopendart.fss.or.kr/mng/userApiKeyListView.do).
3. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from a checkout:

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

The packages are not yet published to PyPI, where an unrelated project owns the name `opendart-mcp`. Outside uv,
install from the repository root with pip, listing every workspace package you need:

```sh
python -m pip install ./packages/sdk                                      # SDK only
python -m pip install ./packages/analysis                                 # analysis only
python -m pip install ./packages/sdk ./packages/analysis                  # SDK and analysis
python -m pip install ./packages/sdk ./packages/analysis ./packages/mcp   # MCP server
```

### MCP server in Docker

The MCP server's container is built on [Docker Hardened Images](https://docs.docker.com/dhi/how-to/use/), which are
pulled from `dhi.io` and need a Docker account. Create a free [Docker account](https://www.docker.com/), generate a
personal access token with read access to public repositories, then authenticate and start the server:

```sh
docker login dhi.io --username YOUR_DOCKER_ID   # paste the token at the password prompt
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
```

The server listens at `http://127.0.0.1:8000/mcp`. Running it natively with `uv run --no-sync opendart-mcp` needs no
Docker account. CI and Renovate also need these credentials as secrets; see the
[CI guide](.github/workflows/README.md#secrets).

Each package's guide covers its configuration and usage.

## Development

Python 3.14+ is required. `uv sync` installs the locked [Just](https://just.systems/) task runner into `.venv`; run it
from the activated environment or with `uv run just`.

```sh
just sync                       # install the workspace and offline test dependencies
just                            # list recipes, including the sdk, analysis, mcp, reference, and ci modules
just check                      # run repository quality checks and every component's offline suite
uv run --no-sync prek install   # install the Git hooks
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/), such as
`fix(sdk): handle an empty response`. See the [CI guide](.github/workflows/README.md) for workflows and the
[scripts guide](scripts/README.md) for generation, release, and quality tooling.

## Related projects

Precedent implementations in the OpenDART ecosystem by [hypn4](https://github.com/hypn4):

- [opendart-fss-python](https://github.com/hypn4/opendart-fss-python): a Python SDK for the OpenDART API.
- [opendart-fss-mcp](https://github.com/hypn4/opendart-fss-mcp): an MCP server for Korea's DART/FSS corporate
  disclosures.
