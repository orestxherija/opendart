---
name: queries
description: "Implement parameterized Python database operations, typed row results, updates, and stable pagination using SQLAlchemy or an existing driver. Use for query contracts; ORM mapping and transaction ownership have separate skills."
---

# Query operations

Keep operation inputs, results, and side effects explicit. Reuse existing
data-access functions or methods; a generic repository abstraction is optional.

## Prerequisites and reference

Python 3.11+ and SQLAlchemy 2.x. [example.py](references/example.py) uses the
[small ORM mapping](../orm/references/example.py) and a caller-owned session.
It exposes a frozen `CustomerRecord`, `get_customer` / `get_customer_async`,
and `update_email` / `update_email_async`. Updates return whether the customer
was found and leave flush/commit to the caller. The helpers do not open sessions,
commit, dispose engines, or retry. Reuse existing mappings when available.

## Implement the requested contract

- Bind values through SQLAlchemy expressions, `text()` parameters, or the
  driver's placeholders. Never interpolate untrusted values into SQL.
  Identifiers are not bind parameters: allowlist columns/order expressions or
  use the driver's identifier-composition API.
- Choose cardinality: zero-or-one, exactly-one, scalar, rows, or a bounded
  iterator. Define missing-row behavior without translating every failure to
  "not found."
- Prevent lost updates where the operation requires it, using an atomic SQL
  expression or deliberate locking/version checks. A transaction alone does
  not make all read-modify-write logic safe from competing writers.
- Select needed columns and convert to DTOs inside the session scope when
  callers must not retain live ORM behavior.
- Give pagination stable ordering with a unique tie-breaker. Keyset pagination
  needs a cursor and consistency contract; offset remains useful for small sets.
- Treat dialect-specific upserts, JSON, collations, and RETURNING as explicit
  capabilities. Shared syntax does not prove identical backend behavior.

Use [errors](../errors/SKILL.md) for classification and
[transactions](../transactions/SKILL.md) when changing atomicity. Large results
belong to [bulk](../bulk/SKILL.md), rather than an unbounded `.all()`.
