# PostgreSQL retry eligibility

The shipped default retries only SQLSTATE `40001` (serialization failure) and
`40P01` (deadlock detected), and only for an operation marked replay-safe. Other
codes remain noneligible unless a separate operation contract justifies a
narrow extension.

Replay the entire transaction, including queries and logic that decided which
writes to make. A successful execute followed by commit-time serialization
failure still needs whole-transaction replay. See
[PostgreSQL's retry guidance](https://www.postgresql.org/docs/current/mvcc-serialization-failure-handling.html).

Do not broadly retry class 08 connection exceptions, unique violations, timeout
cancellations, or all `OperationalError` instances. A lost COMMIT response has
an unknown outcome. An eligible structured rollback error and an unknown network
outcome are different evidence.

Keep external effects outside the callback or use established idempotency.
A database rollback cannot unsend a notification.
