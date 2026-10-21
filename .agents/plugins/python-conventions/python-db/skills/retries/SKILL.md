---
name: retries
description: "Add bounded replay of explicitly replay-safe Python database transactions after eligible SQLite contention or PostgreSQL serialization/deadlock failures. Use for transaction retry policy, not arbitrary statements or uncertain commits."
---

# Whole-transaction retries

The operation that establishes replay safety owns retry policy. Factories,
queries, and classifiers must not independently retry. Default to one attempt
unless replay is explicitly safe for that operation.

## Prerequisites and reference

Python 3.11+, SQLAlchemy 2.x, and the
[error classifier](../errors/references/example.py). Read
[example.py](references/example.py) for `run_transaction` /
`run_transaction_async`, taking a session factory, callback, backend, optional
`RetryPolicy`, and `replay_safe=False`. Each attempt uses a fresh session and
transaction; the callback must leave commit/rollback to the wrapper.

`RetryPolicy` defaults to three maximum attempts, 0.05-second initial backoff,
a 1-second backoff cap, and a 5-second budget for starting attempts/backoff.
Multiple attempts require `replay_safe=True`. These are selectable defaults,
not hard limits on time spent inside a database call.

## Establish the replay contract

- Replay the complete decision/write sequence and re-read decision inputs.
- External email, messages, files, and consumed generators are not rolled back.
  Move effects outside replay or use the application's established idempotency
  contract. Recreate attempt-local ORM state after rollback.
- Retry narrowly classified backend failures. Stop on success, noneligible
  error, exhaustion, budget expiry, or cancellation; propagate the failure.
- Release/roll back the failed session before waiting. Never share one between
  attempts or concurrent callbacks. Bound attempts/backoff and add jitter.
- Coordinate driver/server timeouts with the operation budget; async callers
  may add an outer deadline. Attempt limits cannot interrupt a blocked sync call.
- Do not infer rollback from connection loss during commit. Surface unknown
  outcomes unless established idempotency can resolve them.

Read [SQLite](references/sqlite.md) or [PostgreSQL](references/postgresql.md) for
eligible failures. Verify complete replay, fresh sessions, rollback before sleep,
bounds, and no retries for permanent failures or cancellation.
