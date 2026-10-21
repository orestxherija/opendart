---
name: orm
description: "Map existing SQLite or PostgreSQL tables with SQLAlchemy ORM and make object state and relationship loading predictable. Use for mappings, lazy loading, detached instances, and N+1 queries, not schema migrations."
---

# ORM mappings and loading

Use mapped classes when the application benefits from entity state and
relationships. Core and direct SQL remain useful alongside the ORM; do not
impose a repository hierarchy or map every query result to an entity.

## Prerequisites and starting point

Python 3.11+ and SQLAlchemy 2.x. Read [example.py](references/example.py) for a
typed `DeclarativeBase` / `Mapped` model. `Base` and `Customer` describe an existing
table; importing them performs no I/O or schema creation. Verify names, columns,
nullability, and identity against the actual schema. Constraints in metadata
describe expectations; declaring them does not add them to an existing database.

## Keep database work visible

- Use SQLAlchemy 2.x `select()` and typed `Mapped` declarations. A valid stable
  primary key is required for entity identity; do not invent one for a view
  whose rows are not uniquely identified.
- Choose relationship loading per operation. `selectinload()` is often useful
  for collections; `joinedload()` can multiply rows and may require
  `Result.unique()`. Use `raiseload()` when accidental relationship reads
  should fail instead of issuing unplanned SQL.
- Under asyncio, ordinary attribute access must not trigger implicit database
  I/O. Eagerly load required relationships, refresh explicitly, or deliberately
  use `AsyncAttrs` with awaited access.
- Detached or expired objects may be unable to fetch attributes. Return DTOs
  when callers need stable values after session closure; do not keep sessions
  open merely for serialization.
- The reference factories use `expire_on_commit=False` for loaded values after
  commit. This does not fetch unloaded relationships or guarantee fresh values
  after other writers act. Document stale-value expectations.
- Use projections/Core for reports and large transfers where tracked objects
  add unnecessary work. Bulk DML can bypass per-object state tracking; account
  for identity-map synchronization when mixing them.

[transactions](../transactions/SKILL.md) owns session scope and commit policy.
[queries](../queries/SKILL.md) owns adapters and DTOs; use
[performance](../performance/SKILL.md) when measuring N+1 behavior.

Read [portability](references/portability.md) for cross-backend models. See the
[relationship loading reference](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html)
for strategy-specific behavior.
