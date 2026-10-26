# OpenDART API reference

Read the [published Redoc reference](https://orestxherija.github.io/opendart/).
This directory contains an unofficial OpenAPI description of the
[English OpenDART API](https://engopendart.fss.or.kr/intro/main.do), used to generate
the Python SDK, validate responses, and publish browsable documentation. FSS
operates the API; its guides and service behavior remain authoritative.

## Contents

- [Setup](#setup)
- [Generate offline](#generate-offline)
- [Validate](#validate)
- [Build and view Redoc](#build-and-view-redoc)
- [Refresh guides or audit live responses](#refresh-guides-or-audit-live-responses)

## Setup

Run these commands from the repository root with Python 3.14+, uv, Just, and Node.js 22+ installed:

```sh
uv sync --locked --all-packages --group contracts
just reference sync
```

Python dependencies come from `uv.lock`; `just reference sync` installs the locked
Node dependencies in `scripts/api_reference/`.

## Generate offline

[`scripts/api_reference/build.py`](../scripts/api_reference/build.py) reads the
reviewed [`sources/catalog.json`](sources/catalog.json) snapshot and generates
`openapi.yaml`, `paths/`, `schemas/`, `parameters.yaml`, and `examples.yaml`:

```sh
just reference generate
```

Change the builder or refresh the snapshot, then regenerate. Avoid editing generated YAML directly.

## Validate

```sh
just reference check
```

This runs lint, offline regression tests, and
[`scripts/api_reference/check.py`](../scripts/api_reference/check.py), which checks
freshness, guide coverage, schemas, local references, and JSON/XML examples.
It makes no OpenDART API calls and needs no key.

## Build and view Redoc

[`scripts/api_reference/build-docs.mjs`](../scripts/api_reference/build-docs.mjs)
bundles the specification and embeds Redoc in `site/index.html`:

```sh
just reference build
uv run --no-sync python -m http.server 8000 --directory site
```

Open <http://localhost:8000/>. The [reference workflow](../.github/workflows/check-reference.yml)
validates and builds the same page, then publishes it to GitHub Pages from `main`.

## Refresh guides or audit live responses

To fetch updated public guides with
[`scripts/api_reference/snapshot.py`](../scripts/api_reference/snapshot.py), run
`uv run --no-sync python scripts/api_reference/snapshot.py`, review the snapshot
diff, then repeat generation and validation. This step needs network access.

`just reference contracts` runs
[`scripts/api_reference/contracts/run.py`](../scripts/api_reference/contracts/run.py)
against all operations; `just reference contracts BASE_SHA` limits it to operations
changed since that commit. Set `OPENDART_API__API_KEY` or `OPENDART_API_KEY` first.
Selection and reports go to `contract-results/`. These bounded samples do not
establish every possible upstream response.
