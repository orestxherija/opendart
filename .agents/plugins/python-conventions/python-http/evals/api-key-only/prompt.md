---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, isolation]
---

Our Python service already owns and closes an httpx2.AsyncClient. Replace its static Authorization bearer header with the upstream's X-API-Key header. The validated key is a pydantic.SecretStr named settings.api_key; the existing client factory accepts an httpx2.Auth object. Show the focused auth implementation and wiring in your reply. There is no expiring token and no change to settings loading or request policy.

