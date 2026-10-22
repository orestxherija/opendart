---
type: llm
---

PASS if the wrapper includes commit inside the guarded attempt, rolls back/releases each failed session before waiting, replays the complete transfer with a fresh session, narrowly classifies SQLSTATE 40001/40P01 including wrapped driver errors, and bounds attempts/backoff. Existing connection construction must remain. FAIL if only the last statement or commit is retried, arbitrary OperationalError/disconnects are retried, sessions are reused across attempts, or attempt limits are claimed to interrupt a blocked synchronous call. A reference-based solution must show enough wiring to establish these semantics.
