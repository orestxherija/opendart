---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, isolation]
---

We use httpx2 and already have a configured AsyncClient and valid RetrySettings. Add retries only to submit_payment(), which sends POST /payments. The upstream contract says the same Idempotency-Key and payload replay the original result for 24 hours. A key is provided by our caller once per payment. Show the focused code and one test verifying retries preserve the key. Do not change the client factory or retry other operations.

