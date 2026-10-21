# PostgreSQL client setup

The SQLAlchemy Psycopg dialect supports sync and async engines. Use Psycopg 3,
not a `psycopg2` URL with an async engine. Keep SQLAlchemy as the single pool
owner in this reference stack. See the
[Psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#psycopg).

The reference defaults missing `sslmode` to `verify-full`, which checks the
certificate chain and hostname. Supply the provider CA through `sslrootcert`
when needed. An explicit weaker mode is preserved for deployments such as
isolated local tests; do not mistake encryption alone for server identity
verification. See [libpq TLS](https://www.postgresql.org/docs/current/libpq-ssl.html).
Never log the DSN or returned SQLAlchemy URL.

Per-worker defaults are five pooled connections, zero overflow, ten seconds
checkout waiting, and a ten-second connection timeout. Multiply pool capacity
by workers and replicas, then reserve room for other consumers. `connect_timeout`
is per host; it is not a total operation deadline.

The reference uses pre-ping to replace stale connections during checkout. This
does not recover transactions lost while running. Do not replay on generic
connection errors. Configure statement/lock timeouts for the workload without
leaving unexpected session state behind in a reused pool.

For a hosted proxy, check its pooling mode and prepared-statement support against
the provider's current documentation. Session-level settings, temporary tables,
and prepared statements may require special handling; do not disable features
or stack a second client pool merely because a proxy exists.
