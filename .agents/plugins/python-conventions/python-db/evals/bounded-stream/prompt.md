---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, streaming, isolation]
---

Our existing synchronous SQLAlchemy application exports a very large PostgreSQL SELECT result through a caller-owned Connection inside a caller-owned transaction. Show a context-managed helper yielding row mappings incrementally in batches of about 500. The consumer may stop early or raise. Keep memory bounded by consumption and make the result/cursor close reliably without closing or committing the caller's connection. Do not add ORM models, a connection factory, or retries.
