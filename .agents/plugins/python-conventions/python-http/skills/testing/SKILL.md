---
name: testing
description: "Test outbound Python HTTP integrations with httpx2 mock transports and typed business fakes. Use for client, adapter, auth, retry, streaming, or failure-contract tests."
metadata:
  author: Orest Xherija
  category: python
---

# Test an HTTP boundary

Start with the behavior under test and the existing integration seam. Writing a
test does not require adding a new client factory, settings package, API class,
authentication implementation, or retry layer.

## Prerequisites

Python 3.11+, `httpx2>=2.13,<3`, `pytest>=8`, and AnyIO's pytest plugin.
The minimal [example.py](references/example.py), module
`http_testing_reference`, imports no sibling project modules. Its fixtures and
`Upstream` handler can be used independently.

Use the project's factory with `transport=httpx2.MockTransport(handler)` when
one exists. A standalone test can construct an ordinary `AsyncClient` with
that transport. This exercises request construction and auth without patching
client methods. Mock transports do not implement real socket timing or TLS.

## Two useful boundaries

- Test the upstream adapter against a mock transport: method/path/query/body,
  expected statuses, response validation, and caller-visible exceptions.
- Test business behavior against a small fake satisfying a `Protocol` of the
  methods it uses. No HTTP is needed for this layer.

Handlers record requests and return responses or raise transport exceptions
with `request=request`. Use scripted outcomes to test attempts and transitions.

Mark asynchronous modules with `pytest.mark.anyio` and select the asyncio
backend when the implementation uses asyncio primitives. Own each client inside
the test's event-loop lifetime.

The basic no-network fixture intercepts standard sync and async httpx2
transports. It is a testing safeguard for this library, not a process-wide
network firewall. Explicit `network` tests cover local socket/TLS behavior.
External-provider integration suites remain separately marked and configured.

## Select the relevant reference

| Task | Reference | Project prerequisites |
|---|---|---|
| Basic transports and business fakes | [example.py](references/example.py) | None |
| Backoff and retry outcomes | [retries.py](references/retries.py) | `app.http_retries`, basic test support |
| Token expiry and renewal | [oauth2.py](references/oauth2.py) | `app.http_oauth2` |
| Typed adapter behavior | [billing.py](references/billing.py) | `app.billing_api`, basic test support |
| In-process ASGI calls | [asgi.py](references/asgi.py) | No sibling project modules |

Load only the required example. The repository runs all of them together for
integration coverage and assembles each with its own prerequisites separately.

## Failure tests that expose real behavior

- Replace module-local clocks/sleep/randomness, leaving the event loop's own
  clock alone. Record delays instead of waiting for backoff.
- Use streamed response bodies when testing closure or cancellation. In-memory
  responses may already be consumed and closed, hiding cleanup mistakes.
- For replay tests, use a transport that consumes `request.stream`; calling
  `request.aread()` in the handler can cache the body and hide a consumed stream.
- Verify cancellation releases resources and reaches the caller unchanged.
- Exercise actual timeouts/TLS against a local server when required; a mock
  transport is not evidence of those transport properties.
- ASGITransport does not run application lifespan. Use the application's
  lifespan context explicitly when a service depends on startup resources.

For production changes, consult the corresponding
[client](../client/SKILL.md), [auth](../auth/SKILL.md),
[retries](../retries/SKILL.md), [errors](../errors/SKILL.md),
[api](../api/SKILL.md), or [streaming](../streaming/SKILL.md) skill.
