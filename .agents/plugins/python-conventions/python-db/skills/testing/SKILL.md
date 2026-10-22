---
name: testing
description: "Test Python database client behavior against isolated SQLite or PostgreSQL databases, including constraints, rollback, concurrency, and cleanup. Use for database integration tests; do not add migration tooling or live-service provisioning."
---

# Database client tests

Test database contracts through the actual driver. Business-boundary fakes
cannot establish SQL syntax, constraints, transactions, or cursor cleanup.

## Prerequisites and reference

Python 3.11+, pytest, the application's library, and selected driver. Async tests
need its async pytest plugin. PostgreSQL needs an explicitly supplied disposable
database: an existing CI service or optional Testcontainers fixture may provide
it. Never substitute a production DSN or implicitly provision cloud resources.

[example.py](references/example.py) provides a SQLite `db_engine` fixture and
rollback example using `app.db_client` and `app.db_settings`. Adapt the fixture
to the application; the minimal example is not PostgreSQL verification.

## Choose observable failure cases

- Use `tmp_path` and file-backed SQLite for connection independence, locking,
  and pooling. Ordinary in-memory databases are connection-scoped; a shared
  single connection cannot demonstrate multi-connection concurrency.
- Create only disposable test tables. Fixture DDL is permitted test setup, not
  client startup or a migration architecture. Scope cleanup to test resources.
- Verify multi-write rollback, known unique/foreign-key violations, missing
  rows, result contracts, and release after exceptions/early stream exit.
  Exercise configured transaction/foreign-key behavior, not configuration text.
- Rollback-per-test isolation requires code to respect the injected connection.
  Internal commits, other connections, processes, and concurrency may require
  separate disposable databases/schemas or explicit cleanup.
- Parameterize shared behavior over both backends when the application promises
  both. Add backend-specific type, locking, and retry cases.
- Inject deterministic sleep/randomness where supported for retry scheduling
  tests. Separately verify real driver classification; avoid timing races as the
  only evidence.
- Dispose engines and close sessions/results in fixtures, including failures.

Load [transactions](../transactions/SKILL.md) or [retries](../retries/SKILL.md)
only when their contracts matter. Limit imports using the
[reference registry](../../reference-project.json).
Report observed commands/results. Skipped PostgreSQL tests are not passing
PostgreSQL tests. Authored [model evals](../../evals/README.md) are distinct from
executed deterministic tests.
