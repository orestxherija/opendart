---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, new-skill]
---

Our existing httpx2 client is correctly configured and owned by the service. We need to process a lazy iterable of ten million IDs in order with at most 12 operations running across simultaneous batches. The current asyncio.gather creates one task per ID before any complete. Show a bounded design and describe how callers cancel work. Do not materialize the input or create a task per item.

