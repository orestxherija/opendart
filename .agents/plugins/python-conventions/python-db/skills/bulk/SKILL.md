---
name: bulk
description: "Implement bounded Python database batch writes and streamed reads with explicit cursor and transaction ownership. Use for large transfers, imports, and early-closed result streams; ordinary queries belong to queries."
---

# Batches and result streams

Bound both memory and database resource lifetimes. A fetch size does not bound
total retained objects, pending tasks, transaction duration, or bytes per row.

## Prerequisites and reference

Python 3.11+ and SQLAlchemy 2.x. Read [example.py](references/example.py) for
`insert_batches(connection, table, rows, batch_size=500)` and
`stream_rows(connection, statement, batch_size=500)`, plus async counterparts.
These Core helpers need no ORM model and use caller-owned connections and
transactions. Insert counts represent submitted rows. Streaming contexts yield
mapping results; consume within the context so early exit closes the cursor.

## Choose the transfer contract

- Build bounded batches from iterators; do not first materialize all input.
  Keep statements/row schemas explicit and bind values.
- Decide whether the caller's transaction covers the whole import or each
  chunk. Atomic imports hold resources longer; committed chunks expose partial
  progress and require a restart contract. See
  [transactions](../transactions/SKILL.md) for policy ownership.
- Use server-side/unbuffered results when supported, process incrementally,
  and avoid `.all()` or retained ORM entities. ORM `yield_per`, eager loaders,
  and uniquing have compatibility constraints.
- Keep streams inside the connection/transaction that produced them. Returning
  a cursor after releasing its connection is invalid ownership.
- Iterators and partially delivered output are consumed state. Do not silently
  restart a stream or retry half a bulk transfer.
- Cancellation/early exit must close cursors; the owner still completes the
  transaction and connection cleanup.

Read [SQLite](references/sqlite.md) for lock duration and batching, or
[PostgreSQL](references/postgresql.md) for server-side cursors and the optional
[Psycopg COPY reference](references/postgresql_copy.py). COPY needs Psycopg 3
and an existing caller-owned connection/transaction; it adds no pool.
Verify empty input, boundaries, early closure, and rollback.
