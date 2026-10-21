---
type: llm
---

PASS if the answer implements a focused httpx2.Auth that writes X-API-Key, unwraps SecretStr only when setting the header, and plugs into the existing factory without an additional client lifecycle. FAIL if it adds OAuth/token refresh, retries, a new API adapter, unrelated settings architecture, or logs the secret.

