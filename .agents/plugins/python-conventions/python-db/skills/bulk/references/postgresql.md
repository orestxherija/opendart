# PostgreSQL streams and COPY

For large reads, use the SQLAlchemy streaming context with its connection and
transaction alive. Closing a stream does not end a caller-owned transaction.
Long-lived read transactions can retain snapshots and pool capacity, so bound
consumer lifetime as well as per-fetch row count.

For substantial imports, [postgresql_copy.py](postgresql_copy.py) offers
`copy_rows(connection, table, columns, rows)` and `copy_rows_async`. They require
Psycopg 3 and an existing caller-managed connection and transaction. They compose
identifiers with Psycopg's SQL API and use row adaptation rather than constructing
CSV/SQL from untrusted strings. Returned counts are rows submitted, not proof of
commit. For a schema-qualified name, adapt identifier components explicitly;
do not treat a dotted name as unquoted SQL.

Use the application's existing connection ownership when integrating COPY.
Do not attach a second independent pool underneath SQLAlchemy or commit a raw
driver connection behind SQLAlchemy's transaction manager. Select a direct
Psycopg path only when its lifecycle is explicit.

The copy context closes the protocol; the owner still commits or rolls back.
A consumed generator or partial output is not automatically replayable. See
[Psycopg COPY](https://www.psycopg.org/psycopg3/docs/basic/copy.html).
