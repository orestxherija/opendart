# PostgreSQL performance questions

Separate network round trips, pool checkout, execution, transfer, and decoding.
N+1 queries become especially costly across a network. Inspect SQL and plans
before selecting another driver or enlarging the pool.

Use EXPLAIN for initial inspection. EXPLAIN ANALYZE executes the query; its
measurements also add overhead. Restrict execution to the permitted environment,
and do not assume a transaction rollback undoes every possible side effect.
See [PostgreSQL EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html).

Evaluate query shape, projection, batching, and relevant indexes with realistic
data distribution. Report index/schema recommendations rather than applying
DDL as part of a client-only task. Measure across deployment latency and with
concurrent callers, not only one local loop.

Pool checkout latency can indicate leaked/long transactions, excess admission,
or insufficient capacity. Diagnose before changing limits; an overfull server
may become slower with additional connections.
