# SQLite client setup

Use a file path for ordinary local databases. The shipped settings reject URL
and URI strings; add an explicitly tested URI mode if the operation must open
an existing file without creating it. Do not infer read-only access from a
SELECT-only API.

The reference factory sets foreign-key enforcement on every new connection.
It chooses one cross-version transaction recipe: disable the driver's implicit
BEGIN using `isolation_level=None`, then emit BEGIN through SQLAlchemy's event.
Do not combine it with a second autocommit/isolation-level recipe. Consult the
[SQLAlchemy SQLite transaction guide](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#transactions-with-sqlite-and-the-sqlite3-driver)
when adapting to another supported Python/driver version.

The file-backed reference pool has one connection and no overflow. Its positive
timeout bounds checkout and lock waiting separately. This is a conservative
local default, not a guarantee against contention from other engines/processes.
Raise read capacity only after measuring. Disabling `check_same_thread` permits
cross-thread checkout; it does not make concurrent use of one session safe.

`:memory:` uses a single connection through `StaticPool`. Keep one active unit
of work at a time; use file-backed fixtures for concurrent sessions. Async
SQLite requires `aiosqlite`; it keeps event-loop work moving by using a worker
thread per connection. See [aiosqlite](https://aiosqlite.omnilib.dev/en/stable/).

WAL is not enabled by the factory. It is a persistent database choice with
filesystem implications, not a routine per-connection setting. Evaluate it
separately when the application owns that choice; see
[SQLite WAL](https://www.sqlite.org/wal.html).
