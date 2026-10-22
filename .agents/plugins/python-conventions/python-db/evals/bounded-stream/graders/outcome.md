---
type: llm
---

PASS if a context-managed SQLAlchemy stream uses incremental/streaming result behavior with a bounded fetch batch, yields mappings, and closes the result in a finally/context even after early exit or consumer exceptions. It must leave the connection and transaction caller-owned and show consumption inside all required scopes. FAIL if it materializes all results, returns a live cursor after its scope ends, closes/commits the caller's connection, silently restarts the stream, or promises a fixed byte ceiling from row count alone.
