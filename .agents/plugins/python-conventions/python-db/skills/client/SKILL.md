---
name: client
description: "Build or review Python database client construction: SQLite and PostgreSQL settings, credentials, TLS, engines, pools, timeouts, and cleanup. Use for connection lifecycle changes, not migrations or schema administration."
---

# Database client construction

Preserve the project's driver and sync/async execution model for scoped changes.
For new SQLAlchemy integrations, use SQLite with `sqlite3` or `aiosqlite`, and
PostgreSQL with Psycopg 3. Do not add async solely for presumed speed.

## Prerequisites

Python 3.11+, `SQLAlchemy>=2.0.38,<3`, Pydantic 2.x, and the selected driver.
The SQLite async factory uses pooling options supported from 2.0.38.
Read the [settings contract](../../references/settings-contract.md) only when
adapting configuration. Root configuration loading remains the application's
responsibility.

## Build and own connection resources

- Reuse one engine for its application/worker lifetime. Create it at an explicit
  entry point, not module import. Dispose it at shutdown; await async disposal.
- Use the [settings models](references/settings.py) and [engine factories](references/example.py).
  `build_engine(settings)` and `build_async_engine(settings)` return lazy,
  caller-owned engines. Adapt imports/settings layout without schema creation.
- Give pooling one owner. SQLAlchemy's pool is the reference default. Direct
  Psycopg may use `psycopg_pool`; avoid stacking independent pools.
- Budget connections across processes and replicas, including overflow. Bound
  queued tasks separately. Pool checkout, connecting, lock/statement execution,
  and the complete operation have different deadlines.
- Keep credentials out of logs and verify server identity for hosted databases.
  Reuse existing secret providers. Token refresh belongs at connection creation,
  not a cached global connection.
- Inject an engine/session factory at application seams. Connection ownership
  stays separate from [transaction ownership](../transactions/SKILL.md).

Read only the backend being configured: [SQLite](references/sqlite.md) for file
paths, foreign keys, transaction control, and threads; [PostgreSQL](references/postgresql.md)
for TLS, capacity, stale connections, and proxy compatibility.

Verify connection use and cleanup against the selected backend. Test malformed
settings without connecting; use [testing](../testing/SKILL.md) for behavior that
requires a real driver.
