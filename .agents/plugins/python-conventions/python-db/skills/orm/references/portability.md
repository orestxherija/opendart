# SQLite and PostgreSQL mappings

Portability is a requirement only when the same application supports both.
Shared SQLAlchemy models reduce duplication, but the database determines stored
values, constraints, comparisons, and available functions.

SQLite's flexible typing can accept values PostgreSQL rejects. Define the
application's validation contract and test it against both. Do not use SQLite as
proof of PostgreSQL numeric precision, timezone handling, JSON operators,
collations, or null/unique behavior. See
[SQLite compatibility differences](https://www.sqlite.org/quirks.html).

Map an existing schema accurately. `Integer` is the portable reference identity
for the sample `customers` table; do not assume SQLite BIGINT primary keys have
INTEGER PRIMARY KEY allocation behavior. If existing schemas differ, use an
explicit type variant or separate mapping/query implementation when justified.

SQLAlchemy `DateTime(timezone=True)` does not create identical timezone storage
semantics everywhere. Establish a UTC/offset contract and round-trip it on both
backends. PostgreSQL-specific types/functions are appropriate for PG-only
applications; do not weaken those applications to satisfy unused SQLite support.

Relationship declarations do not enable SQLite foreign-key enforcement; that
is connection configuration owned by [client](../../client/SKILL.md).
