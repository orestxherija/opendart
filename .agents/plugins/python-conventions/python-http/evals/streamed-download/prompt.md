---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, new-skill]
---

Our application owns an httpx2.AsyncClient. Show how to download a potentially 8 GB response to a file without buffering it in memory, including what happens if the status is 404 or the consumer is cancelled halfway through. Leave the client lifecycle unchanged. Do not add retries.

