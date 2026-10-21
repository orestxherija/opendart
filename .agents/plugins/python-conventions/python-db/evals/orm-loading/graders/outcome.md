---
type: llm
---

PASS if the answer explicitly loads Customer.orders in the awaited query (such as selectinload) and materializes plain summaries within the session lifetime, avoiding implicit async I/O and the per-customer N+1 behavior. An equivalent explicit bounded loading strategy is acceptable. It must preserve the existing engine/session factory and mapped classes. FAIL if it merely uses expire_on_commit=False, keeps sessions globally alive, introduces a new repository architecture, or adds unrelated retries or migrations.
