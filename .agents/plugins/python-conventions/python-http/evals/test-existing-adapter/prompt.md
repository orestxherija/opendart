---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, isolation]
---

Write deterministic pytest tests for this existing adapter. Show tests in your reply; keep its implementation and our existing client architecture unchanged. Use httpx2.MockTransport and no real network.
```python
import httpx2


class Catalog:
    def __init__(self, client: httpx2.AsyncClient):
        self.client = client

    async def names(self) -> list[str]:
        response = await self.client.get("/names")
        response.raise_for_status()
        return response.json()["names"]
```
Cover a successful response and an HTTP 503.

