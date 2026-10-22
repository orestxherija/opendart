---
type: llm
---

PASS if the correction preserves sqlite3 and the function/caller ownership, binds email using a qmark placeholder with a one-element parameter sequence, fetches the row, and avoids SQL interpolation. Explicit cursor cleanup is welcome. FAIL if it adds SQLAlchemy/ORM/async, creates/closes the caller's connection, commits internally, introduces retries or a client factory, or tries to escape SQL text instead of binding the value.
