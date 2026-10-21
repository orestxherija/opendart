---
name: transactions
description: "Implement or review Python database transaction and SQLAlchemy session boundaries, rollback, isolation, savepoints, and concurrency. Use when atomicity or session ownership changes; retry scheduling belongs to retries."
---

# Transactions and sessions

Own commit/rollback policy here. Query methods and ORM mappings do not silently
commit. A transaction covers one business unit of work, possibly several queries.

## Prerequisites and reference

Python 3.11+ and SQLAlchemy 2.x. An existing engine is enough; do not recreate
client configuration. Read [example.py](references/example.py) for
`session_factory(engine)` and `async_session_factory(engine)`.

Use `with factory.begin() as session:` or `async with factory.begin() as session:`
to commit on success, roll back on failure, and close the session. Inject that
session into query operations. Closing a read-only session still releases its
connection and ends any implicit transaction.

## Ownership rules

- Engines and factories may be shared; an active session/connection is mutable
  transaction state. Use a separate session per concurrent task or thread.
- `flush()` sends pending work without committing. Autoflush can send writes
  before a query. Keep these effects within the unit of work.
- A failed flush/statement can leave the transaction unusable. Let its owning
  context roll back, or explicitly roll back before reuse in a manual pattern.
  Do not swallow the error and keep issuing statements in that transaction.
- Avoid waiting for HTTP calls or user input while holding locks. Cancellation
  must unwind session/result contexts; do not suppress `CancelledError`.
- Choose isolation for a demonstrated consistency requirement. A savepoint
  contains a sub-operation; it does not commit the outer transaction. Account
  for flushing before `begin_nested()` when isolating an expected row failure.
- Keep uncertain commit outcomes visible. Replay eligibility and backoff belong
  to [retries](../retries/SKILL.md), not automatic commit retry.

Read [SQLite](references/sqlite.md) for transaction mode and locking, or
[PostgreSQL](references/postgresql.md) for isolation and aborted transactions.
Read [orm](../orm/SKILL.md) when expiration or relationship loading affects what
callers may safely use after the scope ends.

Verify multi-operation atomicity, rollback, and connection release. See the
[SQLAlchemy session guide](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
for lifecycle API details.
