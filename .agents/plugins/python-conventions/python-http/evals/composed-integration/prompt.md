---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [composition]
---

Design a small complete integration for a new inventory upstream in our Python 3.11+ service using httpx2 and Pydantic 2. We already have centralized validated settings. GET /items/{id} returns {"id": "...", "stock": 4}; IDs must be non-empty ASCII letters/digits/hyphens, and 404 means item absent. The upstream has no authentication. Show the client lifecycle, typed adapter, meaningful boundary errors, and transport tests in your reply. No retries or pagination are needed.

