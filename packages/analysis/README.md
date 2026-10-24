# OpenDART analysis

[![CI](https://github.com/orestxherija/opendart/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/orestxherija/opendart/actions/workflows/ci.yml?query=branch%3Amain)
[![codecov](https://codecov.io/github/orestxherija/opendart/branch/main/graph/badge.svg?flag=analysis&token=8TTWOC0RC4)](https://codecov.io/github/orestxherija/opendart)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![code style: Ruff](https://img.shields.io/badge/code%20style-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![type check: Pyrefly](https://img.shields.io/badge/type%20check-pyrefly-blueviolet)](https://pyrefly.org/)

Filing parsing, company lookup, and analysis for English OpenDART data. Requires Python 3.14+.

## Table of contents

- [Design](#design)
- [Install](#install)
- [Guides](#guides)
- [Maintainer notes](#maintainer-notes)

## Design

The package works on bytes, records, and callbacks supplied by the caller. It needs neither the OpenDART SDK
(`opendart-sdk`) nor the MCP server (`opendart-mcp`), and it never imports either one, so it works with any data
source. Its only dependencies are AnyIO, defusedxml, and Pydantic. The MCP server depends on this package and on the
SDK, and binds the two together.

Capabilities live in subpackages; importing `opendart_analysis` itself loads nothing else.
`opendart_analysis.documents` turns the ZIP archive returned by `disclosures.document` into an outline, paged
Markdown, typed tables, and search results, using the filing's own English headings and labels.
`opendart_analysis.directory` parses the corporation-code archive returned by `disclosures.corporation_codes` and
resolves company names and codes. `opendart_analysis.reports` finds a company's latest periodic report and resolves
requested periods, reading filings through caller-supplied [data access](docs/data-access.md). Modules under
`opendart_analysis.domain` are internal.

## Install

From a checkout, run `uv sync --locked --all-packages`. The package can also be installed directly with
`python -m pip install ./packages/analysis` from the repository root. Its distribution name is `opendart-analysis`
and its import name is `opendart_analysis`.

Applications that download filings with the SDK install both distributions, `opendart-sdk` and `opendart-analysis`.

## Guides

- [Filing documents](docs/documents.md): read a filing downloaded with the SDK, the documents API, archive limits, and
  the caching `DocumentStore`.
- [Company directory](docs/directory.md): parse the corporation-code archive, search it, and resolve names and codes.
- [Data access](docs/data-access.md): how workflows receive upstream data, freshness hints, record protocols,
  exceptions, and the direct-SDK recipe.
- [Periodic reports](docs/reports.md): find a company's latest periodic report and resolve requested periods.
- [Service catalog](docs/catalog.md): metadata for all 85 OpenDART services and the corporate-event vocabulary.

## Maintainer notes

MCP tool and resource output schemas embed the document models and the domain vocabulary, such as `Market`, `Period`,
and `Unit`. Changing their fields, values, defaults, or descriptions is an MCP wire change: run `just mcp components`
and review the component lock before merging. Keep one class per type
rather than copying models into MCP.

Tests use synthetic archives built in `tests/documents/conftest.py` and `tests/domain/directory_data.py` and run offline
without the SDK or MCP. `tests/directory/` exercises the directory guide's example against a synthetic archive, and
`tests/reports/` runs the data-access recipe with a duck-typed client and the reports workflow with synthetic records
and a fixed date.

Data access follows one pattern as workflows move here from MCP. Name each callback Protocol for its operation and give
it a frozen query value, a keyword-only `volatility`, and a result of records or `None`; add only the record fields a
calculation reads. MCP binds each Protocol in `opendart_mcp.core.upstream` with a return annotation naming the
analysis Protocol, which is what makes its type check prove that SDK records conform, and maps `Volatility` to its
cache lifetimes. MCP adapters translate analysis exceptions into server errors, keeping messages that name tools in MCP.
