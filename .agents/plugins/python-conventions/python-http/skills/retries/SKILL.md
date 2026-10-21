---
name: retries
description: "Add or review bounded retries for outbound Python httpx2 operations: replay safety, Retry-After, backoff, idempotency keys, and total deadlines. Use for transient failures and throttled upstream calls."
metadata:
  author: Orest Xherija
  category: python
---

# Retry one HTTP operation

Use an existing client and add policy only to an operation that needs it.
Changing retries does not require changing client construction, credentials, or
the caller's exception interface.

## Prerequisites

Python 3.11+, `httpx2>=2.13,<3`, `pydantic>=2.7,<3`.
The [reference](references/example.py) becomes `app.http_retries` and consumes
`SettingsGroup`, `Attempts`, and `Seconds` from the
[settings contract](../../references/settings-contract.md).
There is no required sibling HTTP module.

## Operation contract

1. Pass `send_with_retries` a zero-argument callable and `RetrySettings`.
   The callable creates a fresh request, including a replayable body, on each
   attempt. Creating a new Request around an exhausted iterator is not replay.
2. Retry only operations known to be safe to repeat. The helper recognizes
   idempotent methods, an `Idempotency-Key` header, or a connect failure before
   transmission. A key is meaningful only when the upstream documents support.
3. Generate one key per logical operation and reuse it across attempts.
   If a durable job can repeat the operation, carry the same logical key across
   that job's attempts too. A helper cannot infer the provider's deduplication
   window or whether a transaction has already committed.
4. Bound attempts and total elapsed time. `max_attempts` includes the first
   call; an outer `asyncio.timeout` covers every attempt and wait. Preserve
   cancellation.
5. Honor `Retry-After` in seconds or HTTP-date form. If it exceeds
   `max_retry_after`, return the response instead of retrying early. Otherwise
   use exponential backoff with full jitter.
6. Close discarded responses before waiting. Return the last response or raise
   the last transport error; the caller checks status and decides its final
   error contract.
7. Apply retries at one layer. Nested retrying jobs and clients multiply
   attempts and can duplicate work.

## Default policy

| Outcome | Eligible operation |
|---|---|
| `ConnectError`, `ConnectTimeout` | Any method: no request sent |
| Read/write errors and timeouts, `RemoteProtocolError` | Replay-safe operation |
| 408, 429, 502, 503, 504 | Replay-safe operation |
| Other statuses/errors, including `PoolTimeout` and 500 | One attempt under this default policy |

These are chosen defaults, not a universal classification of every provider.
An upstream's documented 500 behavior may justify a narrower adapted policy.
Investigate local capacity or leaked responses for pool exhaustion.

Defaults: 3 total attempts, 0.5-second initial backoff ceiling, 30-second maximum
backoff, and 60-second maximum Retry-After. Each wait is uniform between zero
and the current exponential ceiling.

## Conditional composition

- [auth](../auth/SKILL.md): only when a 401 requires credential renewal.
- [errors](../errors/SKILL.md): only when translating the final outcome, after
  retries finish.
- [concurrency](../concurrency/SKILL.md): only for shared limits or fan-out.
- [streaming](../streaming/SKILL.md): when request/response bodies stream.
- [observability](../observability/SKILL.md): when defining safe diagnostics or
  distinguishing attempt latency from logical-operation latency.
- [testing](../testing/SKILL.md): controlled time and scripted outcomes.

Read [references/example.py](references/example.py) to implement the helper.
Its retry logs omit URLs, headers, bodies, and exception messages. Use trusted
static labels when adding upstream or operation context.
