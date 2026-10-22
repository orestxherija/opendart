---
name: streaming
description: Stream outbound HTTP uploads and downloads with explicit response ownership, size limits, cancellation, and replay constraints.
---

# HTTP streaming

Use streaming when response or request bodies should not be held in memory.
Choose the owner of the client, response, source, and destination before adding
helpers. Keep the response context open until the consumer finishes; returning
an iterator from inside an already-exited context loses that ownership.

## Prerequisites and routing

- The reference requires Python 3.11+, `httpx2>=2.13,<3`, and an existing
  `httpx2.AsyncClient`. It imports no project settings or sibling references.
- Read [the transfer reference](references/example.py) for a bounded download to
  an async sink or upload from an async generator. The caller owns the client
  and destination; the upload helper consumes and closes its source generator.
- Consult [python-http:client](../client/SKILL.md) only for client lifecycle or
  timeout changes, [python-http:auth](../auth/SKILL.md) when an auth flow may read
  or resend bodies, and [python-http:retries](../retries/SKILL.md) only when replay
  is needed and supported by the upstream.
- Consult [python-http:testing](../testing/SKILL.md) for transport fixtures and
  [python-http:concurrency](../concurrency/SKILL.md) when transfers share a budget.

## Preserve backpressure and ownership

Await each sink write before reading another chunk. Bound source chunk size and
total transferred bytes, and avoid `aread()`, `.content`, or `.json()` on an
unbounded body. Chunking decoded output alone does not cap decompressor memory.
The download reference requests identity encoding and rejects compressed
responses; if compression is required, use a decoder with an explicit bounded
output strategy and enforce limits on decoded bytes.

Per-phase client timeouts are not an overall transfer deadline. Place
`asyncio.timeout(...)` around transfer plus source/sink work when an overall
deadline is required. On failure or cancellation, close responses and sources,
propagate cancellation, and discard partial destination data according to the
application contract. For files, write to a temporary sibling and rename only
after successful validation; choose async file I/O or thread offloading for
blocking filesystem operations.

## Treat replay as a separate contract

The reference explicitly disables redirects and makes a single request. A
streamed upload is generally one-shot. A retry must reopen its source from the
beginning, retain the same upstream-supported idempotency key, and account for
the possibility that the upstream accepted the first attempt. The reference
does not promise rollback or resume.

The OAuth reference defaults to `replay_after_401=False`, which leaves streamed
bodies unbuffered. Its `True` option buffers the complete body for replay; reserve
that option for bodies with a known small upper bound. Audit any existing auth
or transport retry behavior before assuming a helper makes only one attempt.

Test body failures, size limits, early consumer failure, cancellation, and source
and response closure. A mock transport may itself buffer uploads, so use a small
custom `AsyncBaseTransport` when testing incremental upload behavior.
