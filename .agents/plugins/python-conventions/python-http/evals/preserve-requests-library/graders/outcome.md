---
type: llm
---

PASS if the response keeps requests and adds an explicit finite timeout to requests.get while preserving status checking and JSON return behavior. FAIL if it imports httpx2, adds async code, introduces a client factory/settings package, or expands the change beyond the requested timeout.

