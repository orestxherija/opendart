"""Bounded Core batch operations using a caller-owned connection/transaction.

Suggested module: app.db_bulk. Batch limits count rows, not bytes. Input row sizes
and database parameter limits also matter. These helpers do not commit, retry,
or materialize the entire input. A stream retains the connection/transaction
until its context exits; exit it explicitly even when a consumer stops early.
"""

from collections.abc import AsyncIterator, Iterable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from itertools import islice

from sqlalchemy import Table, insert
from sqlalchemy.engine import Connection, MappingResult
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncMappingResult
from sqlalchemy.sql import Executable


def _batches(
    rows: Iterable[Mapping[str, object]],
    batch_size: int,
) -> Iterator[list[dict[str, object]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    iterator = iter(rows)
    while batch := list(islice(iterator, batch_size)):
        yield [dict(row) for row in batch]


def insert_batches(
    connection: Connection,
    table: Table,
    rows: Iterable[Mapping[str, object]],
    *,
    batch_size: int = 500,
) -> int:
    """Insert batches atomically within the caller's transaction; count inputs."""
    submitted = 0
    for batch in _batches(rows, batch_size):
        connection.execute(insert(table), batch)
        submitted += len(batch)
    return submitted


async def insert_batches_async(
    connection: AsyncConnection,
    table: Table,
    rows: Iterable[Mapping[str, object]],
    *,
    batch_size: int = 500,
) -> int:
    """Async database I/O; the input iterator must itself be quick/nonblocking."""
    submitted = 0
    for batch in _batches(rows, batch_size):
        await connection.execute(insert(table), batch)
        submitted += len(batch)
    return submitted


@contextmanager
def stream_rows(
    connection: Connection,
    statement: Executable,
    *,
    batch_size: int = 500,
) -> Iterator[MappingResult]:
    """Stream a SELECT and close its cursor on early exit or failure."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    result = connection.execute(statement.execution_options(yield_per=batch_size))
    try:
        yield result.mappings()
    finally:
        result.close()


@asynccontextmanager
async def stream_rows_async(
    connection: AsyncConnection,
    statement: Executable,
    *,
    batch_size: int = 500,
) -> AsyncIterator[AsyncMappingResult]:
    """Use async iteration; close the result before returning the connection."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    result = await connection.stream(
        statement,
        execution_options={"yield_per": batch_size},
    )
    try:
        yield result.mappings()
    finally:
        await result.close()
