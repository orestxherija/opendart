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

![opendart-analysis design: callers bind data access to the SDK, a cache, or test data; capability packages build on
the domain, the service catalog, periodic reports, and extracts; the upstream and errors conventions are leaves; the
MCP server and Python applications bind the SDK](docs/architecture.svg)

The package works on bytes, records, and callbacks supplied by the caller. It needs neither the OpenDART SDK
(`opendart-sdk`) nor the MCP server (`opendart-mcp`), and it never imports either one, so it works with any data
source. Its only dependencies are AnyIO, defusedxml, and Pydantic. The MCP server depends on this package and on the
SDK, and binds the two together; Python applications that download with the SDK do the same with a few lines of code.

Capabilities live in subpackages; importing `opendart_analysis` itself loads nothing else:

| Subpackage | Capability |
| --- | --- |
| `documents` | Parse the filing archive from `disclosures.document` into an outline, paged Markdown, tables, and search results; `DocumentStore` downloads, parses, and caches filings. |
| `directory` | Parse the corporation-code archive, search it, and resolve names and codes to a structured `Resolution`; `DirectoryLoader` keeps it loaded and refreshed. |
| `catalog` | Metadata for all 85 OpenDART services, value kinds of their fields, and the corporate-event vocabulary. |
| `reports` | Find a company's latest periodic report and resolve requested periods. |
| `extracts` | Fetch one periodic-report service for a company and period and read its fields. |
| `financials` | Statements over periods, derived metrics, indicators, equity investments, preliminary earnings, and peers. |
| `events`, `filings` | Interpret material-event reports, and search the filing index within page budgets. |
| `ownership`, `capital`, `debt`, `dividends`, `profile`, `governance` | Periodic-report analysis of control, share capital, debt securities, dividends, company facts, and governance. |
| `calendar` | Forward corporate-action dates and debt maturities for one company or a watchlist. |

Two conventions are shared by every workflow. `opendart_analysis.upstream` defines how workflows receive upstream data:
typed async callables, the catalog-keyed `FetchService`, record protocols that name only the fields a calculation
reads, and `Volatility` freshness hints for the caller's cache. `opendart_analysis.errors` defines the failure
categories. Modules under `opendart_analysis.domain` are internal. Pure parsing and calculation sit below the workflows
that fetch, and [`importlinter.toml`](../../importlinter.toml) enforces that layering.

Edit the [draw.io source](docs/architecture.drawio), then export it as SVG to update
[the README diagram](docs/architecture.svg). Keep the source and SVG together.

## Install

The distribution name is `opendart-analysis` and the import name is `opendart_analysis`. From a checkout, run
`uv sync --locked --package opendart-analysis` for this package alone, or `uv sync --locked --all-packages` for the
whole workspace. Outside uv, run `python -m pip install ./packages/analysis` from the repository root.

Applications that download filings with the SDK install both distributions, `opendart-sdk` and `opendart-analysis`,
at the same version: `python -m pip install ./packages/sdk ./packages/analysis`. The root README compares the
[installation choices](../../README.md#choose-a-package).

## Guides

- [Contracts](docs/contracts.md): data units, missing data, provenance, structured ambiguity, task ownership,
  configuration, exceptions, and versioning, which hold across every capability.
- [Filing documents](docs/documents.md): read a filing downloaded with the SDK, the documents API, archive limits, and
  the caching `DocumentStore`.
- [Company directory](docs/directory.md): parse the corporation-code archive, search it, resolve names and codes,
  and keep it loaded and refreshed with `DirectoryLoader`.
- [Data access](docs/data-access.md): how workflows receive upstream data, freshness hints, record protocols,
  exceptions, and the direct-SDK recipe.
- [Periodic reports](docs/reports.md): find a company's latest periodic report and resolve requested periods.
- [Service catalog](docs/catalog.md): metadata for all 85 OpenDART services and the corporate-event vocabulary.
- [Financial statements](docs/financials.md): statements over periods with restatement merging and derived metrics,
  published indicators, equity investments, preliminary earnings, and peer comparison.
- [Company profiles](docs/profile.md): reference facts from the company overview and the latest periodic report.
- [Dividends](docs/dividends.md): dividend history by measure, share class, and fiscal year from annual reports, with
  units converted and earlier reports chained.
- [Debt securities](docs/debt.md): maturity ladders of bonds, commercial paper, and hybrid securities, the issuance
  record with coupons and ratings, and upcoming maturities.
- [Ownership and control](docs/ownership.md): the controlling group's stake, minority shareholders, a free-float
  estimate, changes of control, and 5% holder and insider reports.
- [Capital structure](docs/capital.md): share counts by class, treasury stock, share issuances and reductions, and the
  use of money raised, from one periodic report.
- [Governance](docs/governance.md): audit opinions, fees, and auditor changes, board composition, executives, pay, and
  workforce from one periodic report, with red flags.
- [Periodic-report extracts](docs/extracts.md): fetch one periodic-report service for a company and period, read its
  all-string fields, and list source filings.
- [Corporate events](docs/events.md): read a company's material events from major-issue and registration reports,
  interpreted into headlines, key terms, dated actions, and flags.
- [Filing discovery](docs/filings.md): search the filing index by company, market, category, and title, merged newest
  first within page budgets.
- [Corporate-action calendar](docs/calendar.md): forward corporate-action dates and debt maturities for one company
  or a watchlist, with lookback windows, merged repeats, and per-company coverage.

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
