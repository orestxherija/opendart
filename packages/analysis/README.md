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
