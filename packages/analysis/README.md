# OpenDART analysis

[![CI](https://github.com/orestxherija/opendart/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/orestxherija/opendart/actions/workflows/ci.yml?query=branch%3Amain)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![code style: Ruff](https://img.shields.io/badge/code%20style-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![type check: Pyrefly](https://img.shields.io/badge/type%20check-pyrefly-blueviolet)](https://pyrefly.org/)

Filing parsing, company resolution, the OpenDART service catalog, and analysis workflows for English OpenDART data.
It works on bytes, records, and async callables supplied by the caller, and never imports or depends on the
[OpenDART SDK](https://github.com/orestxherija/opendart/tree/main/packages/sdk) (`opendart-sdk`).

## Table of contents

- [Installation](#installation)
- [Usage](#usage)
- [Modules](#modules)
- [Development](#development)

## Installation

The package is not yet published to a package index. Install it from a checkout of the
[repository](https://github.com/orestxherija/opendart); it requires Python 3.14+. The distribution name is
`opendart-analysis` and the import name is `opendart_analysis`.

```sh
uv sync --locked --package opendart-analysis   # uv, from the workspace
python -m pip install ./packages/analysis      # pip, from the repository root
```

To fetch data with the SDK, install `opendart-sdk` alongside it at the same version, for example with
`uv sync --locked --package opendart-sdk --package opendart-analysis` or
`python -m pip install ./packages/sdk ./packages/analysis`. Both packages are released together, and the record
protocols follow the SDK's field names.

## Usage

Resolve free-text company references against the corporation-code directory, with no API key or network access:

```python
from datetime import UTC, date, datetime

from opendart_analysis.directory import CorpRecord, Directory, resolve

# parse_directory(archive) reads records like these from OpenDART's corporation-code ZIP archive.
records = [
    CorpRecord("00126380", "삼성전자", "SAMSUNG ELECTRONICS CO.,LTD", "005930", date(2025, 12, 1)),
    CorpRecord("00164742", "현대자동차", "HYUNDAI MOTOR CO", "005380", date(2026, 3, 31)),
    CorpRecord("00164788", "현대모비스", "HYUNDAI MOBIS CO.,LTD", "012330", date(2025, 3, 18)),
]
directory = Directory.build(records, loaded_at=datetime.now(UTC))

for text in ("005930", "samsung electronics", "Hyundai"):
    resolution = resolve(directory, text)
    print(text, resolution.reason, [match.record.corp_code for match in resolution.candidates])
# 005930 code ['00126380']
# samsung electronics exact ['00126380']
# Hyundai ambiguous ['00164742', '00164788']
```

Workflows that need OpenDART data never receive an SDK client. Each takes the upstream operations it needs as
keyword-only async callables typed by protocols in `opendart_analysis.upstream`, and reads the results through record
protocols that name only the fields it uses. The SDK, a cache, a database, or test data can supply them, and requests
a workflow cannot answer raise exceptions from `opendart_analysis.errors`.

## Modules

Importing `opendart_analysis` loads nothing; import from its subpackages. Modules under `opendart_analysis.domain`
are internal.

| Subpackage | Contents |
| --- | --- |
| `documents` | Parse a filing archive into an outline, paged Markdown, tables, and search results; `DocumentStore` downloads, parses, and caches filings. |
| `directory` | Parse the corporation-code archive, search it, and resolve names and codes; `DirectoryLoader` keeps it loaded and refreshed. |
| `catalog` | Metadata for all 85 OpenDART services, the value kinds of their fields, and the corporate-event vocabulary. |
| `reports` | Find a company's latest periodic report and resolve requested periods. |
| `extracts` | Fetch one periodic-report service for a company and period, read its fields, and list source filings. |
| `financials` | Statements over periods with restatements merged, derived metrics, indicators, equity investments, preliminary earnings, and peer comparison. |
| `events` | Material events from major-issue and registration reports, interpreted into headlines, key terms, dated actions, and flags. |
| `filings` | Search the filing index by company, market, category, and title within page budgets. |
| `ownership` | The controlling group's stake, minority shareholders, a free-float estimate, changes of control, and 5% holder and insider reports. |
| `capital` | Share counts by class, treasury stock, share issuances and reductions, and the use of money raised. |
| `debt` | Maturity ladders of bonds, commercial paper, and hybrid securities, the issuance record, and upcoming maturities. |
| `dividends` | Dividend history by measure, share class, and fiscal year from annual reports. |
| `profile` | Reference facts from the company overview and the latest periodic report. |
| `governance` | Audit opinions, fees, and auditor changes, board composition, executives, pay, and workforce, with red flags. |
| `calendar` | Forward corporate-action dates and debt maturities for one company or a watchlist. |
| `upstream`, `errors` | The data-access convention every workflow follows, and the shared failure categories. |

## Development

From a checkout, `just analysis test` runs the offline tests, and `just analysis check` adds linting, type checking,
and a check of the generated service catalog. Run `just analysis generate` to regenerate the catalog after the API
catalog or the SDK naming rules change. Workspace setup and the other packages are described in the
[repository README](https://github.com/orestxherija/opendart/blob/main/README.md).
