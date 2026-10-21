# SQLite transaction behavior

Use one consistent transaction recipe. The
[client reference](../../client/references/example.py) takes ownership of BEGIN
rather than depending on legacy driver's selective implicit transactions.
Retain it when using savepoints or transactional tests; do not mix it with
independent driver-autocommit overrides.

SQLite has one writer per database file. Keep write transactions short and avoid
unrelated awaits while holding them. A deferred read can fail when upgraded to a
write after another connection changes its snapshot. Repeating the last UPDATE
inside that transaction is insufficient: roll back and reassess the whole unit
under the operation's replay contract.

`BEGIN IMMEDIATE` can acquire write intent before reading, but moves contention
to transaction start and should be selected deliberately for the workload. It
is not the universal default for all reads. See
[SQLite isolation](https://www.sqlite.org/isolation.html).

A pooled connection is not a concurrent session. In-memory shared-connection
fixtures are especially unsuitable for testing independent transactions.
