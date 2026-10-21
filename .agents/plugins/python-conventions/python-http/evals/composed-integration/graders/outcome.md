---
type: llm
---

PASS if the result composes owned/closed client lifecycle, explicit timeouts, a typed adapter with identifier validation before URL construction, 404 handling distinct from unavailable/malformed responses, and MockTransport tests. FAIL if it adds authentication or retries despite the prompt, creates clients per operation, accepts "."/".." IDs, or tests with real network calls.

