---
name: client
description: "Build or review reusable outbound Python httpx2 clients: settings, ownership, timeouts, connection pools, TLS, and test transport injection. Use when changing client construction or lifecycle."
metadata:
  author: Orest Xherija
  category: python
---

# HTTP client construction

Use the project's existing HTTP conventions for a scoped change. Adopt httpx2
for new integrations following this plugin; migrate another library only when
migration is part of the requested work.

## Prerequisites

Python 3.11+, `httpx2>=2.13,<3`, and `pydantic>=2.7,<3`.
The reference consumes `SettingsGroup`, `PoolSize`, and `Seconds` from the
[shipped settings contract](../../references/settings-contract.md). Reuse
matching project definitions. Consult `python-settings:python-settings` only
when adding or changing root configuration or its sources.

## Build the client

1. Give each upstream its own configuration group: base URL, credentials,
   timeouts, and pool limits. Nest that group in the existing settings object.
2. Use `build_client(settings, *, auth=None, verify=True, transport=None)`.
   The reference returns an `httpx2.AsyncClient`. For an end-to-end synchronous
   workflow, adapt it to `httpx2.Client` and `BaseTransport`.
3. The caller owns and closes the client. Reuse it for a service lifespan or
   an entry-point context manager. Keep resource creation out of imports and
   request loops; cached settings do not imply cached resources.
4. Timeouts bound connect/read/write/pool phases. Apply an outer
   `asyncio.timeout` around a complete operation when it needs a total deadline,
   including queueing, attempts, and backoff.
5. Keep server verification enabled. A custom `ssl.SSLContext` goes in
   `verify=`; client certificates are described in `auth`.
6. A static bearer token may come from `settings.token`. The factory wraps it
   in `BearerAuth`; supplying both that token and `auth=` is an error.
7. Redirects are enabled only for calls whose contract needs them. Check status
   before parsing a response, after handling any expected endpoint-specific
   status. Retry policy belongs to the individual operation.
8. `transport=` is the test seam. An explicit production transport owns its own
   proxy/TLS/pool configuration and can bypass factory-level options; configure
   and test those responsibilities explicitly.

## Defaults and capacity

The reference preserves httpx2 defaults: 5-second phase timeouts, 100 maximum
connections, 20 keepalive connections, and HTTP/2 disabled. Tune per upstream.
Keep keepalive connections within the connection ceiling.

HTTP/2 is opt-in and requires `httpx2[http2]`. Its multiplexed requests and
HTTP/1.1 fallback mean connection count is not a reliable request-concurrency
limit. Use a separate limiter when bounding work; the client factory does not
own task scheduling.

## Consult only when needed

| Task | Skill |
|---|---|
| API keys, token refresh, or mTLS | [python-http:auth](../auth/SKILL.md) |
| Repeating a transiently failed operation | [python-http:retries](../retries/SKILL.md) |
| Fan-out, shared limits, queueing, or cancellation | [python-http:concurrency](../concurrency/SKILL.md) |
| Typed upstream methods | [python-http:api](../api/SKILL.md) |
| Failure translation | [python-http:errors](../errors/SKILL.md) |
| Uploads or downloads without buffering whole bodies | [python-http:streaming](../streaming/SKILL.md) |
| Transport-level tests | [python-http:testing](../testing/SKILL.md) |

Read [references/example.py](references/example.py) when implementing or changing
the factory. Adapt package names and the existing settings layout; retain the
ownership, validation, and injection contracts.
