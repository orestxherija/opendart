---
name: errors
description: "Translate outbound httpx2 and response-validation failures into stable Python exceptions at an upstream boundary. Use when designing or changing the failure contract seen by callers."
metadata:
  author: Orest Xherija
  category: python
---

# HTTP failure boundaries

Translate failures in the function or adapter that owns an upstream operation.
An existing function can be that boundary; introducing a client factory, API
class, or retries is not a prerequisite.

## Prerequisites

Python 3.11+, `httpx2>=2.13,<3`, `pydantic>=2.7,<3`.
[references/example.py](references/example.py) becomes `app.http_errors`.
It has no project-module prerequisites and consumes no settings helpers.

## Caller contract

Use three outcomes: `UpstreamUnavailable` (no usable answer),
`UpstreamRejected` (the request/data/permissions must change), and
`UpstreamContractError` (an unexpected response requires investigation).
Each upstream may subclass these with a shared upstream base, allowing callers
to catch by upstream, outcome, or both.

Handle expected statuses such as a lookup's 404 before general translation.
Use a specific exception when the caller has a distinct response to that case.

| Failure | Outcome |
|---|---|
| HTTP status 429 or 5xx | Unavailable |
| Other 4xx, including a final 401 | Rejected |
| Network, protocol, proxy, redirect-limit or phase timeout failures | Unavailable |
| Response decoding or Pydantic body-validation failure | Contract error |
| An operation deadline raised inside this boundary | Unavailable |
| Calling-code bugs and cancellation | Propagate unchanged |

Keep exception handling around the HTTP operation and response parsing.
A broad catch around business code can turn programming errors into upstream
outages. If retries are present, translate after they finish; a retry decision
and the caller's final outcome are different classifications.

## Preserve evidence without leaking it

`raise translate(error, TYPES) from error` preserves the cause for debugging.
The translated message omits queries, headers, and bodies; its path can still
contain an identifier.

Exception chaining does **not** sanitize the full traceback. The original
HTTPStatusError may include its full URL, and ValidationError may include
response data. Public responses and routine logs should use allowlisted
operation/status/type fields, without `str(error)`, `exc_info`, or a formatted
cause chain. Follow [observability](../observability/SKILL.md) when implementing
that logging boundary; retain full traces only in an appropriately restricted,
redacted debugging channel.

Log at the layer that takes action, rather than at each layer that re-raises.
Return an empty result only when that is the actual upstream contract, not as a
substitute for reporting every failure.

## Consult only when needed

- [api](../api/SKILL.md): creating typed upstream methods and response models.
- [retries](../retries/SKILL.md): changing which attempts repeat.
- [auth](../auth/SKILL.md): renewing rejected credentials.
- [testing](../testing/SKILL.md): testing outcome mappings.

Read the local [reference](references/example.py) when implementing the
taxonomy or translator; adapt exception names to the upstream.
