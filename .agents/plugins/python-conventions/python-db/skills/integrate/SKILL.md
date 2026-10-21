---
name: integrate
description: "Integrate existing SQLite or PostgreSQL databases into a Python application, selecting only the client, ORM, query, transaction, and testing components needed. Use for a new or coordinated client integration, not schema migration or database provisioning."
---

# Integrate a database client

Inspect the driver, execution model, settings, schema, lifecycle, and tests.
Preserve the user's stack and schema ownership. New reference integrations use
SQLAlchemy Core/ORM with SQLite `sqlite3`/`aiosqlite` and PostgreSQL Psycopg 3.
Synchronous applications do not require async conversion.

No sibling skill or agent is mandatory. Each reference declares dependencies.
Apply the workflow directly when the host has no tools.

## Select necessary components

Identify operations, backend(s), atomic units, and caller return types. If one
application uses local SQLite and hosted PostgreSQL, identify its promised
shared behavior. Do not impose portability on unrelated applications.

| Change | Guidance |
|---|---|
| Engine, credentials, TLS, pool, lifecycle | [client](../client/SKILL.md) |
| Session scope, commit/rollback, isolation | [transactions](../transactions/SKILL.md) |
| Existing-table mappings and loading | [orm](../orm/SKILL.md) |
| Queries, results, pagination | [queries](../queries/SKILL.md) |
| Failure translation | [errors](../errors/SKILL.md) |
| Explicitly replay-safe transaction retry | [retries](../retries/SKILL.md) |
| Measured latency/query/pool work | [performance](../performance/SKILL.md) |
| Batches and result streams | [bulk](../bulk/SKILL.md) |
| Logs, metrics, tracing | [observability](../observability/SKILL.md) |
| Changed behavior/backend tests | [testing](../testing/SKILL.md) |

Load only guidance whose contracts change and only its relevant backend
references. A lookup does not automatically need retries, bulk support, an ORM,
or a repository class. Examples describe contracts, not mandatory module layout.

Keep engines caller-owned, sessions scoped to work, and commit outside query
helpers. Do not call `create_all()` during client construction. Migrations,
schema evolution, and provisioning remain separate future work.

Run appropriate available checks. Report resulting behavior, observed tests,
and any backend not exercised. Do not claim PostgreSQL verification from a
SQLite-only run or model-eval success from authored rubrics.
