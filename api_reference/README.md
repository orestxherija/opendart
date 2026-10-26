# OpenDART API reference

An unofficial OpenAPI description of the
[English OpenDART API](https://engopendart.fss.or.kr/intro/main.do), published as the
[Redoc reference](https://orestxherija.github.io/opendart/). It generates the Python SDK and
validates responses. FSS operates the API; its guides and service behavior remain authoritative.

## Table of contents

- [Layout](#layout)
- [Generate and validate](#generate-and-validate)
- [Build Redoc](#build-redoc)
- [Refresh or audit](#refresh-or-audit)

## Layout

- `sources/`: the reviewed snapshot of the public guides and the live-audit record.
- `openapi.yaml`, `paths/`, `schemas/`, `parameters.yaml`, `examples.yaml`: generated from `sources/`; do not
  edit them directly.
- [`scripts/api_reference/`](../scripts/api_reference/): the builder, checks, Redoc bundler, live contract
  audit, and their tests.

## Generate and validate

Run from the repository root with Python 3.14+, uv, Just, and Node.js 22+:

```sh
uv sync --locked --all-packages --group contracts
just reference sync       # locked Node dependencies
just reference generate   # regenerate the YAML from sources/
just reference check      # lint, tests, freshness, schemas, references, and examples
```

Validation is offline and needs no API key.

## Build Redoc

```sh
just reference build
uv run --no-sync python -m http.server 8000 --directory site
```

Open <http://localhost:8000/>. CI builds the same page and publishes it to GitHub Pages from `main`.

## Refresh or audit

- `uv run --no-sync python scripts/api_reference/snapshot.py` refetches the public guides; review the diff,
  then regenerate and validate.
- `just reference contracts [BASE_SHA]` audits live responses for all operations, or only those changed
  since `BASE_SHA`. Set `OPENDART_API__API_KEY` first; reports go to `contract-results/`.
