---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [negative]
---

This question concerns incoming requests to our FastAPI service, not requests to any upstream. Explain how a dependency can reject a missing X-API-Key request header with HTTP 401. We already have our server settings and authentication policy; give a minimal illustrative dependency only.

