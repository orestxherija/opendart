---
type: llm
---

PASS if the reply provides a synchronous SQLAlchemy SQLite factory with per-connection foreign-key enforcement, a coherent Python 3.11 transaction recipe (for example isolation_level=None plus an explicit BEGIN event without a conflicting autocommit recipe), bounded lock waiting, and caller-owned disposal. It must not run create_all, add migration tooling, enable WAL, or introduce async. A supported existing-file/read-only adaptation is allowed but not required. FAIL if the factory shares an active Session globally or claims pool size makes SQLite support simultaneous writers.
