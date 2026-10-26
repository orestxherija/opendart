# OpenDART SDK

[![CI](https://github.com/orestxherija/opendart/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/orestxherija/opendart/actions/workflows/ci.yml?query=branch%3Amain)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![code style: Ruff](https://img.shields.io/badge/code%20style-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![type check: Pyrefly](https://img.shields.io/badge/type%20check-pyrefly-blueviolet)](https://pyrefly.org/)

Typed asynchronous Python client for the English OpenDART service at `https://engopendart.fss.or.kr/engapi`.
It covers all 85 documented services with validated Pydantic models. Requires Python 3.14+.

## Table of contents

- [Installation](#installation)
- [Usage](#usage)
- [Services](#services)
- [Errors](#errors)
- [Development](#development)

## Installation

The package is not yet published to a package index. Its distribution name is `opendart-sdk` and its import name is
`opendart`. From a checkout of the [repository](https://github.com/orestxherija/opendart), install it into the uv
workspace, or with pip from the repository root:

```sh
uv sync --locked --package opendart-sdk
python -m pip install ./packages/sdk
```

## Usage

```python
import asyncio
from opendart import OpenDART


async def main():
    async with OpenDART() as client:
        company = await client.disclosures.company(corporation_code="00126380")
        print(company.corporation_name)

        accounts = await client.financial_statements.fnltt_singl_acnt(
            corporation_code="00126380", fiscal_year="2025", report_period="11011"
        )
        for account in accounts.list or []:
            print(account.account_name, account.current_period_amount)


asyncio.run(main())
```

`OpenDART()` reads its settings from `OPENDART_API__*` environment variables, starting with the required
`OPENDART_API__API_KEY`; pass an `OpenDARTSettings` instance to configure it in code instead. A dotenv file is read
only when requested explicitly, as in `OpenDART(Settings(_env_file=".env").api)`, and nothing loads at import time.
Await every call, and keep one client for the application's lifetime on its event loop.

## Services

| Resource | Services | Contents |
| --- | ---: | --- |
| `client.disclosures` | 4 | Filing search, company overview, filing documents, and the corporation-code directory |
| `client.periodic_reports` | 30 | Key information from periodic reports |
| `client.financial_statements` | 7 | Financial statements, indicators, and XBRL from periodic reports |
| `client.equity_disclosures` | 2 | Major shareholder and executive shareholding reports |
| `client.major_issues` | 36 | Reports on major issues |
| `client.securities_registration` | 6 | Securities registration statements |

Methods are named after their upstream routes in snake case, such as `fnltt_singl_acnt`; `disclosures.search` and
`disclosures.corporation_codes` are the exceptions. Arguments and response fields use readable names, such as
`corporation_code` for `corp_code`; `model_dump(by_alias=True)` restores the OpenDART names. The three ZIP downloads,
`disclosures.corporation_codes()`, `disclosures.document()`, and `financial_statements.fnltt_xbrl()`, return `bytes`;
[`opendart-analysis`](https://github.com/orestxherija/opendart/tree/main/packages/analysis) can parse them. The
[published API reference](https://orestxherija.github.io/opendart/) documents every service, parameter, and field.

## Errors

Every SDK failure inherits `OpenDARTError`, which exposes `operation`, `status` (the OpenDART status code, if any),
and `http_status`. Messages never include the API key, request URLs, or upstream message text.

- `NoDataError`: status `013`, the query matched no data.
- `FileUnavailableError`: status `014`, the requested file is unavailable.
- `QuotaExceededError`: status `020`, the API key's quota is exhausted.
- `ServiceUnavailableError`: status `800`, upstream maintenance.
- `APIRejectedError`: the API rejected the key, parameters, or permissions.
- `APIError`: the base of the errors above, also raised for any other non-success status.
- `UnavailableError`: a transport failure or HTTP 429/5xx; quota and maintenance errors are also subclasses.
- `RejectedError`: any other HTTP 4xx response.
- `ContractError`: an unexpected HTTP status, redirect, encoding, or response shape; its subclass
  `ResponseTooLargeError` reports a response over the configured byte limit.
- Pydantic `ValidationError`: invalid arguments, raised before any request is sent.

`disclosures.search` returns one page; request the next with `page_number` until the response's `total_page`. The
client makes one attempt per call and never retries, so retrying is up to the caller.

## Development

From a synced checkout (`just sync`), `just sdk test` runs the offline tests and `just sdk check` adds linting, type
checking, and generated-file freshness. Models and resources are generated from the checked-in
[OpenAPI reference](https://github.com/orestxherija/opendart/tree/main/api_reference) by `just sdk generate`; edit the
reference or the [generator](https://github.com/orestxherija/opendart/blob/main/scripts/sdk/generate_sdk.py), never
the generated files. See the
[repository README](https://github.com/orestxherija/opendart/blob/main/README.md) for the rest of the workspace.
