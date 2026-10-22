"""Real SQLite fixture and rollback test; copy selected parts into your tests.

Suggested module: db_testing_reference (or tests/conftest.py). Requires pytest,
SQLAlchemy, and the shipped db_client/db_settings examples. Schema creation here
is confined to a disposable test database. Application clients do not own DDL.
Use the PostgreSQL test guidance when production behavior depends on PostgreSQL.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db_client import build_engine
from app.db_settings import SQLiteSettings


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = build_engine(SQLiteSettings(database=str(tmp_path / "test.sqlite")))
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY)"))
        yield engine
    finally:
        engine.dispose()


def test_rollback_releases_connection(db_engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="abort"):
        with db_engine.begin() as connection:
            connection.execute(text("INSERT INTO sample (id) VALUES (:id)"), {"id": 1})
            raise RuntimeError("abort")
    with db_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sample")) == 0
