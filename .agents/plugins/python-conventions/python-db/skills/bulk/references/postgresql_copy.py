"""Selected PostgreSQL COPY path for a caller-owned Psycopg connection.

Suggested module: app.db_copy. Requires psycopg>=3.2.1,<4. The caller opens a
transaction (for example with connection.transaction()) and commits/rolls back.
COPY avoids per-row statement round trips. Errors propagate to that boundary.
Use a dedicated direct-driver integration or a carefully owned SQLAlchemy raw
connection; never add another pool just to use this function.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from psycopg import AsyncConnection, Connection, sql


def _statement(table: str, columns: Sequence[str]) -> sql.Composed:
    if not table or not columns or any(not column for column in columns):
        raise ValueError("COPY needs a table and at least one named column")
    # A qualified name needs separately quoted schema and table identifiers;
    # this reference accepts one table name in the caller's selected schema.
    return sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
    )


def copy_rows(
    connection: Connection[Any],
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> int:
    """Count submitted rows; identifiers and values are handled separately."""
    statement = _statement(table, columns)
    count = 0
    with connection.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


async def copy_rows_async(
    connection: AsyncConnection[Any],
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> int:
    """Async COPY; the input iterator must not perform blocking work."""
    statement = _statement(table, columns)
    count = 0
    async with connection.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            await copy.write_row(row)
            count += 1
    return count
