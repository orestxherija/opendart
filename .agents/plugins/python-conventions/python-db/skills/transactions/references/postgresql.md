# PostgreSQL transaction behavior

Use the database's existing isolation default unless correctness requires a
change. Row locks last until the transaction ends; avoid network calls and long
processing inside that scope. Use consistent lock acquisition order when
multiple resources must be updated.

After a PostgreSQL statement failure, the transaction normally requires rollback
before more statements can succeed. To contain an expected row-level failure,
use a deliberate savepoint and catch the exception outside its context. A
savepoint does not commit the outer unit.

Repeatable-read/serializable behavior differs from SQLite. In particular,
serialization failures can occur at commit. Keep the entire business decision
inside the retry callback if [retries](../../retries/SKILL.md) are warranted.
SQLSTATE `40001` identifies serialization failure and `40P01` deadlock detection;
replay is still an operation decision. See
[PostgreSQL serialization handling](https://www.postgresql.org/docs/current/mvcc-serialization-failure-handling.html).

Connection loss during COMMIT does not prove failure or success. Preserve that
uncertainty for caller reconciliation instead of silently repeating writes.
