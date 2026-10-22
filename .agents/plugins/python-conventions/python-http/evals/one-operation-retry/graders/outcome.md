---
type: llm
---

PASS if retries wrap only submit_payment, use the supplied key unchanged for every attempt, keep the payload replayable, bound attempts, and leave other calls and client construction untouched. FAIL if a new key is generated per attempt, all client traffic is retried, POST is retried without referencing the stated upstream contract, or unrelated architecture is introduced.

