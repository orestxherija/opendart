---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, postgresql, retries]
---

My synchronous SQLAlchemy service uses PostgreSQL with Psycopg 3 and a sessionmaker named factory. The operation transfer(session, source_id, destination_id, amount) reads both balances then writes both; it does not commit or perform external effects, and it is safe to run again after rollback. It occasionally raises SQLSTATE 40001, including during commit. Show a bounded wrapper and wiring in your reply that retries the whole transaction with a fresh session, includes backoff, and stops on other failures. Keep 40P01 eligible too. A lost connection during COMMIT must not be silently replayed. Existing connection construction stays as it is.
