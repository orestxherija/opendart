# Database settings contract

Read this when adapting the client factory. The references use Pydantic settings
groups, not a new environment loader. Reuse the project's root settings object
and secret source. Consult `python-settings:python-settings` only when changing
root configuration, environment/TOML sources, or settings caching.

| Suggested module | Shipped source | Responsibility |
|---|---|---|
| `app.db_settings` | [settings.py](../skills/client/references/settings.py) | Validated SQLite and PostgreSQL connection settings |
| `app.db_client` | [example.py](../skills/client/references/example.py) | Engine construction; caller owns disposal |

Copy only required references and adapt the `app` import prefix. Installing the
plugin does not provide runtime modules or install application libraries.

`SQLiteSettings(database=..., timeout_seconds=5)` accepts a file path or
`:memory:`, not a URL/URI. Ordinary SQLite opening may create a missing file.
For access that must never create a database, adapt the factory to the driver's
explicit existing-file/read-only URI mode; checking path existence is not an
atomic substitute. The timeout bounds lock waiting and reference pool checkout,
not the complete operation.

`PostgreSQLSettings` accepts `dsn: SecretStr`, `pool_size=5`, `max_overflow=0`,
`pool_timeout_seconds=10`, and `connect_timeout_seconds=10`. It normalizes supported
PostgreSQL URLs to the Psycopg SQLAlchemy dialect and defaults an absent `sslmode`
to `verify-full`. An explicitly supplied mode is preserved; verify that its
security matches the deployment. Treat a returned URL as secret-bearing.

Reveal credentials only when constructing the driver connection. Avoid raw
Pydantic validation payloads: `SecretStr` and hidden validation-input text do not
make every serialization of a failed settings input safe.

Runtime baseline: Python 3.11+, `SQLAlchemy>=2.0.38,<3`, and Pydantic 2.x. SQLite sync uses
the standard library; async SQLite additionally needs `aiosqlite`. PostgreSQL
needs Psycopg 3 in either mode. `sqlalchemy[asyncio]` supplies async integration
dependencies where needed. Use the consuming project's supported version bounds.
