---
name: concurrency
description: Bound outbound HTTP fan-out, shared in-flight work, and queueing deadlines without allocating one task per input.
---

# HTTP concurrency

Use this skill when several outbound operations need a concurrency budget. Keep
an existing sequential call simple. Connection-pool size limits connections;
concurrency limits active operations; requests per second requires a separate
rate limiter. HTTP/2 multiplexing makes these limits especially different.

## Prerequisites and routing

- The reference requires Python 3.11+ and an asyncio event loop. It has no
  third-party libraries, project settings, or sibling-skill prerequisites.
- Reuse the application's existing client. Consult
  [python-http:client](../client/SKILL.md) only when changing its ownership,
  connection pool, or per-phase timeouts.
- Consult [python-http:retries](../retries/SKILL.md) only for repeatable calls that
  need retries. Decide whether a shared permit covers each attempt or the entire
  retry sequence; do not acquire the same permit at both levels.
- Consult [python-http:streaming](../streaming/SKILL.md) when a permit must remain
  held until a response body is consumed and closed.

## Apply a budget at the right scope

Read [the bounded-worker reference](references/example.py) for finite batches.
`map_bounded(items, operation, limit=..., limiter=..., timeout=...)` consumes a
lazy iterable using at most `limit` tasks and returns results in input order.
Results still use memory proportional to the number of items. For unbounded
feeds or very large results, use a bounded queue and a downstream consumer
instead of collecting a list.

A per-batch limit does not protect an upstream from many concurrent batches.
Create one semaphore per upstream in the application's lifetime and share it
among those call sites. All participating calls must use it, including single
calls outside `map_bounded`. It is local to one event loop and process, so scale
the budget for replicas or use an external coordinator when a global limit is
required. Never create the semaphore inside each request and call it shared.

The optional timeout covers the whole batch, including waiting for a shared
permit. A per-request read timeout does not bound that wait. Propagate
cancellation; let workers finish cleanup before returning. The reference cancels
siblings on a worker failure and raises an `ExceptionGroup`; it does not return
partial successes. Choose a different explicit outcome contract when independent
item failures should be retained.

For HTTP/1.1, leave pool capacity for other users of the client. A concurrency
limit greater than the pool can be intentional, but then pool waiting contributes
to latency and may hit the pool timeout. Measure before adjusting either limit.
