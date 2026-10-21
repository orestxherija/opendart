# SQLite retry eligibility

The shipped classifier treats `SQLITE_BUSY` and its extended result codes as
candidates for whole-transaction replay. It inspects structured error codes,
not text such as "database is locked." It conservatively excludes `SQLITE_LOCKED`,
constraint errors, and unknown exceptions.

Busy timeout already waits for some lock conflicts. Additional bounded replay
is useful only when the operation is safe to repeat. After a stale-snapshot
failure, restart the transaction and re-read decision inputs. Waiting longer
inside the old snapshot cannot make it current. See
[SQLite isolation](https://www.sqlite.org/isolation.html).

First investigate long transactions and unbounded writers. Retrying is not a
substitute for capacity control. The local reference's one-connection pool does
not prevent another process from contending on the file.
