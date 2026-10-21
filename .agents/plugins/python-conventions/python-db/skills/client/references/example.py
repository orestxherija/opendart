"""Lazy synchronous and asynchronous engine factories.

Create one engine per configured database and process. The application owns
``engine.dispose()`` or ``await engine.dispose()`` after all sessions close.
No connections are opened at import or construction time. SQLAlchemy owns the
pool; do not add psycopg_pool underneath it.

File SQLite uses one connection and no overflow to bound local contention.
Raise that limit deliberately for read concurrency after measuring workload.
Separate engines/processes can still contend for SQLite's single writer.
``:memory:`` uses StaticPool and must only have one active unit of work; it is
not a substitute for file-database concurrency tests. WAL is never enabled as
an incidental connection side effect.

This chooses one cross-version SQLite transaction recipe: disable the driver's
implicit BEGIN and emit BEGIN from SQLAlchemy. Do not combine this recipe with
``autocommit=False`` or execution_options(isolation_level=...).
"""

from typing import Protocol

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from app.db_settings import DatabaseSettings, PostgreSQLSettings


class _Cursor(Protocol):
    def execute(self, statement: str) -> object: ...

    def close(self) -> None: ...


class _SQLiteConnection(Protocol):
    isolation_level: str | None

    def cursor(self) -> _Cursor: ...


def _sqlite_connect(
    connection: _SQLiteConnection, connection_record: ConnectionPoolEntry
) -> None:
    connection.isolation_level = None
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _sqlite_begin(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN")


def _configure_sqlite(engine: Engine) -> None:
    event.listen(engine, "connect", _sqlite_connect)
    event.listen(engine, "begin", _sqlite_begin)


def build_engine(settings: DatabaseSettings) -> Engine:
    """Build a sync engine; the owner must dispose it during shutdown."""
    if isinstance(settings, PostgreSQLSettings):
        return create_engine(
            settings.sqlalchemy_url(),
            connect_args={"connect_timeout": settings.connect_timeout_seconds},
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout_seconds,
            pool_pre_ping=True,
            hide_parameters=True,
        )
    url = URL.create("sqlite+pysqlite", database=settings.database)
    connect_args = {"timeout": settings.timeout_seconds, "check_same_thread": False}
    if settings.database == ":memory:":
        engine = create_engine(
            url,
            connect_args=connect_args,
            poolclass=StaticPool,
            hide_parameters=True,
        )
    else:
        engine = create_engine(
            url,
            connect_args=connect_args,
            pool_size=1,
            max_overflow=0,
            pool_timeout=settings.timeout_seconds,
            hide_parameters=True,
        )
    _configure_sqlite(engine)
    return engine


def build_async_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build an asyncio engine; dispose it before its event loop is closed."""
    if isinstance(settings, PostgreSQLSettings):
        return create_async_engine(
            settings.sqlalchemy_url(),
            connect_args={"connect_timeout": settings.connect_timeout_seconds},
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout_seconds,
            pool_pre_ping=True,
            hide_parameters=True,
        )
    url = URL.create("sqlite+aiosqlite", database=settings.database)
    connect_args = {"timeout": settings.timeout_seconds, "check_same_thread": False}
    if settings.database == ":memory:":
        engine = create_async_engine(
            url,
            connect_args=connect_args,
            poolclass=StaticPool,
            hide_parameters=True,
        )
    else:
        engine = create_async_engine(
            url,
            connect_args=connect_args,
            pool_size=1,
            max_overflow=0,
            pool_timeout=settings.timeout_seconds,
            hide_parameters=True,
        )
    _configure_sqlite(engine.sync_engine)
    return engine
