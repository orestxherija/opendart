---
type: llm
---

PASS if the tests inject MockTransport through an owned/closed AsyncClient, verify the successful names and an HTTPStatusError on 503, and run async tests with a supported approach (asyncio.run or a named pytest async plugin). FAIL if they require a real network, replace the adapter, invent a new factory, or import unrelated auth/retry/billing helpers.

