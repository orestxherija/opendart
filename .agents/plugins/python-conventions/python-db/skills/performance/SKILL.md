---
name: performance
description: "Diagnose Python database client performance through query counts, execution plans, result volume, ORM loading, connection waiting, and representative benchmarks. Use for measured client-side performance work, not automatic index or server changes."
---

# Database client performance

Start with the slow operation and representative workload. Separate connection
waiting, SQL execution, transfer, ORM object creation, and application processing.
Record a baseline. No new library or sibling skill is mandatory.

## Investigate the limiting work

1. Inspect query count/shape, returned rows/columns, transaction duration, and
   pool checkout waiting. Driver benchmarks do not explain N+1 queries.
2. Inspect plans with realistic parameters/data. Start with plain EXPLAIN.
   EXPLAIN ANALYZE executes the statement; use it only in a permitted safe
   environment, accounting for write effects and workload cost.
3. Reduce avoidable round trips and transfer using deliberate relationship
   loading, projections, batching, and appropriate pagination. Validate results.
4. Tune pool capacity against concurrency and database limits. More connections
   can increase contention. Bound admitted work as well as connection count.
5. Compare throughput, tail latency, memory, and contention under representative
   load. Report cache/network conditions and tradeoffs, not a universal winner.

Use [orm](../orm/SKILL.md) for loading, [bulk](../bulk/SKILL.md) for bounded
transfers, and [observability](../observability/SKILL.md) for safe timing.
Read [SQLite](references/sqlite.md) or [PostgreSQL](references/postgresql.md) for
backend constraints affecting the measurement.

Diagnose missing indexes/schema limitations with evidence. Applying production
indexes, schema changes, or server reconfiguration is outside client optimization
unless separately requested and supported by appropriate guidance.
