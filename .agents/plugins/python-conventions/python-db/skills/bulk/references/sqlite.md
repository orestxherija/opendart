# SQLite batches and streams

Use bounded parameter batches with a caller-selected transaction boundary.
Executing many writes with a commit per row adds unnecessary work; a transaction
covering an entire very large import may hold write access too long. The right
boundary depends on atomicity and restart requirements, not only batch size.

Respect the actual SQLite build's bound-variable limits when constructing large
multi-value statements. Executemany and multi-value SQL can have different
limits and performance. Do not hard-code an old universal parameter ceiling.

SQLite has no remote server-side cursor. Incremental fetching still avoids a
Python list of all results, but a transaction/cursor can remain open for the
whole consumer loop. Close on early exit and avoid unrelated long work while
holding it. Bound row size or process large blobs separately if a byte ceiling
is required; a row-count batch is not a byte limit.
