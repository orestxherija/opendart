# SQLite performance questions

Measure query plans, repeated reads, Python row/object work, and lock wait time.
`EXPLAIN QUERY PLAN` is useful for spotting scans and temporary sorts; investigate
representative SQL before increasing pool capacity. See
[SQLite plan inspection](https://www.sqlite.org/eqp.html).

More connections or async tasks do not create multiple simultaneous writers.
Batch related writes inside the caller's chosen transaction while avoiding long
transactions that monopolize write access.

WAL can permit readers alongside a writer but still has one writer. Long read
transactions can delay checkpoint progress. It also depends on same-host shared
memory and is not a general solution for a network-mounted database file.
Changing journal mode is persistent: report evidence and scope that decision
separately from tuning query code. See [WAL behavior](https://www.sqlite.org/wal.html).

Use file-backed, realistically sized data for benchmarks involving concurrency
or I/O. An in-memory single-connection test removes key costs from the workload.
