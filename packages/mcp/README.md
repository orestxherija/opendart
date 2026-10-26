# OpenDART MCP

[![CI](https://github.com/orestxherija/opendart/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/orestxherija/opendart/actions/workflows/ci.yml?query=branch%3Amain)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![code style: Ruff](https://img.shields.io/badge/code%20style-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![type check: Pyrefly](https://img.shields.io/badge/type%20check-pyrefly-blueviolet)](https://pyrefly.org/)

A local [Model Context Protocol](https://modelcontextprotocol.io/) server for the regulatory filings of Korean
companies, served over Streamable HTTP on the loopback interface. It is built on [FastMCP](https://gofastmcp.com/) and
reads [OpenDART](https://engopendart.fss.or.kr/) through `opendart-sdk` and `opendart-analysis`. Every tool accepts a
company by name (English or Korean), stock code, or DART corp code.

## Table of contents

- [Tools](#tools)
- [Run](#run)
- [Configuration](#configuration)
- [Connect a client](#connect-a-client)
- [Development](#development)

## Tools

| Tool | What it answers |
| --- | --- |
| `find_company` | Ranked matches in the DART company directory. |
| `get_company_profile` | Names, codes, market, CEO, industry, fiscal year end, and the latest periodic report. |
| `search_filings` | Filings for one company or market-wide, by category, date window, and title text. |
| `read_filing` | The outline, sections, and text search of an original filing. |
| `get_financials` | Statements, summaries with derived margins, ratios, equity investments, and preliminary earnings. |
| `compare_companies` | A peer table of key accounts or ratios for up to 20 companies. |
| `get_corporate_events` | Capital raises, convertible debt, buybacks, M&A, asset deals, distress, and legal events. |
| `get_ownership` | Largest shareholders, control changes, 5% holder and insider reports, and a free-float estimate. |
| `get_capital_structure` | Share counts, treasury stock, capital changes, and the use of raised funds. |
| `get_debt_profile` | A maturity ladder of debt securities and the issuance record. |
| `get_dividends` | Dividends per share, payout, and yields as filed, across fiscal years. |
| `get_governance` | Auditor and opinion, board, executives, compensation, and employees, with red flags. |
| `get_corporate_action_calendar` | Upcoming subscription, record, meeting, listing, conversion, and maturity dates. |

Every tool is read-only and returns Markdown text plus `structuredContent` that matches its `outputSchema`. Two
optional tools, `list_services` and `call_service`, reach all 85 OpenDART services; set
`OPENDART_MCP_TOOLS__ENABLE_SERVICE_TOOLS=true` to register them.

Eight `opendart://` resources expose company profiles, filing indexes and sections, reference vocabularies, and server
status. Eleven prompts package workflows such as `company_briefing`, `earnings_review`, and `summarize_filing`.
`get_financials`, `compare_companies`, and `get_corporate_action_calendar` also link to
[MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview) for hosts that render them.

## Run

From the repository root, run the server natively:

```sh
uv sync --locked --all-packages
uv run --no-sync opendart-mcp  # or: just mcp run
```

Or in Docker. The base images come from Docker Hardened Images, so log in to `dhi.io` first with your Docker ID and a
personal access token that can read public repositories:

```sh
docker login dhi.io --username YOUR_DOCKER_ID
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
```

To give the container an API key, set `OPENDART_API_KEY_FILE` to the absolute path of a file that holds only the key
(readable by UID 10001) and add `-f packages/mcp/compose.secrets.yml` to the `up` command.

Either way the server listens at `http://127.0.0.1:8000/mcp`, and `GET /health` reports its status and version.
Without an API key it still lists every component, and tool calls explain how to configure one. The first start
downloads the company directory, which can take minutes; until then, tools accept 8-digit corp codes.

## Configuration

Settings are read from the environment at startup; nested groups use a double underscore. The main ones follow;
[`settings.py`](https://github.com/orestxherija/opendart/blob/main/packages/mcp/src/opendart_mcp/settings.py) lists
every setting.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENDART_API__API_KEY` | none | OpenDART API key; or the file `/run/secrets/OPENDART_API__API_KEY`. |
| `OPENDART_MCP_HTTP__HOST` | `127.0.0.1` | Bind address: `127.0.0.1`, `localhost`, or `0.0.0.0` inside containers. |
| `OPENDART_MCP_HTTP__PORT` | `8000` | Listener port; Compose also publishes it on `127.0.0.1`. |
| `OPENDART_MCP_TOOLS__ENABLE_SERVICE_TOOLS` | `false` | Register the `list_services` and `call_service` tools. |
| `OPENDART_MCP_TOOLS__ELICIT_AMBIGUOUS_COMPANY` | `true` | Ask hosts that support elicitation to choose among matching companies. |
| `OPENDART_MCP_UPSTREAM__TIMEOUT` | `30` | Timeout of OpenDART JSON requests, in seconds. |
| `OPENDART_MCP_UPSTREAM__MAX_CONCURRENCY` | `5` | Simultaneous OpenDART requests. |
| `OPENDART_MCP_DIRECTORY__CACHE_DIR` | `~/.cache/opendart-mcp` | Company directory cache; follows `XDG_CACHE_HOME`. |
| `OPENDART_MCP_DOCUMENTS__CACHE_CHARS` | `4000000` | Bound of the rendered filing cache, in characters. |

## Connect a client

Start the server, then point a client that supports Streamable HTTP at it, as the repository's
[`.mcp.json`](https://github.com/orestxherija/opendart/blob/main/.mcp.json) does:

```json
{
  "mcpServers": {
    "opendart": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

## Development

- `just mcp test` runs the MCP test suite; `just mcp check` adds lint, type checks, and the component lock check.
- `just mcp smoke` smoke-tests an isolated native server over HTTP.
- `just mcp conformance` runs the official MCP conformance suite in both protocol eras; it needs Node.js.
- `just mcp components` checks component versions against `components.lock.json`; `just mcp lock` records changes.

See the [repository README](https://github.com/orestxherija/opendart/blob/main/README.md) for the workspace and the
[CI README](https://github.com/orestxherija/opendart/blob/main/.github/workflows/README.md) for CI and image publishing.
