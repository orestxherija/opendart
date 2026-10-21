# python-db

Client-side database conventions for Python 3.11+, with SQLite for local work
and PostgreSQL for hosted databases. Version **0.1.0**. SQLAlchemy 2.x Core and
ORM share connection and transaction ownership; synchronous and asynchronous
applications are both supported. Declares `python-settings ^1.0` as an
installation dependency; root settings loading is only needed when that task is
in scope.

## Install and use

After adding this marketplace, install in Claude Code:

```text
/plugin install python-db@python-conventions
```

Ask naturally, or invoke `/python-db:integrate customers` or
`/python-db:review src/db.py`. Preserve an existing database library for a scoped
change. The reference stack is a default for new work, not a migration mandate.

| Backend | Synchronous driver | Async driver |
|---|---|---|
| SQLite | Python's `sqlite3` | `aiosqlite` |
| PostgreSQL | Psycopg 3 | Psycopg 3 async |

Install Python dependencies in the consuming application separately. The plugin
ships instructions and reference code; it does not install an `app` package.
Choose dependencies for the application's execution mode:

```sh
# Synchronous SQLite (sqlite3 is built in).
python -m pip install 'SQLAlchemy>=2.0.38,<3' 'pydantic>=2.7,<3'
# Async SQLite: add the async integration and driver.
python -m pip install 'SQLAlchemy[asyncio]>=2.0.38,<3' 'aiosqlite>=0.20,<1'
# PostgreSQL, sync or async: add Psycopg 3 (binary is one installation option).
python -m pip install 'psycopg[binary]>=3.2.1,<4'
# Async PostgreSQL also uses the SQLAlchemy asyncio extra.
python -m pip install 'SQLAlchemy[asyncio]>=2.0.38,<3'
```

Use synchronous code for a synchronous application. Async SQLite uses a worker
thread per connection and does not increase SQLite's write concurrency.

## Choose the skill for the task

| Skill | Owns | Minimal reference prerequisites |
|---|---|---|
| [client](skills/client/SKILL.md) | Configuration, credentials, TLS, engines, pools, disposal | SQLAlchemy, selected driver, Pydantic |
| [transactions](skills/transactions/SKILL.md) | Sessions, commit/rollback, isolation, savepoints | SQLAlchemy; caller-owned engine |
| [orm](skills/orm/SKILL.md) | Mappings, relationships, loading, object state | SQLAlchemy |
| [queries](skills/queries/SKILL.md) | Parameterized operations, typed results, pagination | SQLAlchemy; example model |
| [errors](skills/errors/SKILL.md) | Structured failure classification and safe translation | SQLAlchemy; standard-library SQLite errors |
| [retries](skills/retries/SKILL.md) | Whole-transaction replay, eligibility, bounds | SQLAlchemy; errors reference |
| [performance](skills/performance/SKILL.md) | Query counts, plans, pool contention, measurement | Existing application and database |
| [bulk](skills/bulk/SKILL.md) | Bounded batches and stream ownership | SQLAlchemy; caller-owned connection |
| [testing](skills/testing/SKILL.md) | Real-backend tests, isolation, cleanup | pytest and selected database driver |
| [observability](skills/observability/SKILL.md) | Safe operation timings and bounded diagnostics | Standard library; application callback |
| [integrate](skills/integrate/SKILL.md) | Select components for an integration | Only selected guidance |
| [review](skills/review/SKILL.md) | Read-only inspection with concrete findings | Only selected guidance |

Each skill is usable independently and loads backend details only when needed.
The [reference registry](reference-project.json) lists source files, suggested
module names, and direct prerequisites. See the [settings contract](references/settings-contract.md)
when adapting configuration. ORM mappings describe existing tables; they do not
create them during client startup.

If one application uses both backends, test its shared behavior against both.
SQLite tests do not establish PostgreSQL locking, constraint, or type semantics.
Separate applications may use their backend's capabilities without imposing a
portability abstraction.

## Validation and optional review

The [reviewer agent](agents/db-reviewer.md) offers a scoped read-only review on
hosts with agent support. No skill requires agents, shell execution, or hooks.

From the repository root, assemble a selected reference profile and validate:

```sh
python tests/project.py build/python-db --plugin python-db --profile orm-client
python scripts/validate_marketplace.py
pytest tests/python_db
```

The ordinary test run exercises SQLite and skips PostgreSQL unless a dedicated
local database is supplied. CI runs PostgreSQL against a disposable service.
To exercise an existing local test service (never an application database):

```sh
PYTHON_DB_TEST_POSTGRES_DSN='postgresql://postgres:postgres@127.0.0.1:5432/python_db_test?sslmode=disable' pytest tests/python_db
```

Tests restrict PostgreSQL connections to the dedicated local `python_db_test`
database and create/drop isolated test schemas there. Disabling TLS in that
loopback test URL is not the hosted-client default.

Executable reference tests check code behavior and resource ownership. The
[behavioral evals](evals/README.md) separately exercise skill selection and
composition. They are authored cases, not passing model results; paid model
runs are opt-in and are not part of deterministic CI.

## Boundaries

This release covers clients accessing existing databases. Alembic, migrations,
production schema creation, database provisioning, backups, and server
administration are outside its scope. Tests may create disposable tables.
Performance work may identify a missing index and supply evidence, while applying
schema changes belongs to a later, separately scoped addition.

Direct Psycopg, `sqlite3`, and existing third-party drivers remain valid choices.
Reference implementations use SQLAlchemy; do not introduce ORM entities,
repository interfaces, async conversion, or retry wrappers where unnecessary.
The optional PostgreSQL COPY reference uses a caller-owned Psycopg connection;
it is not a second pool/lifecycle implementation.
