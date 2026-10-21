---
max_turns: 26
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, composition, sqlite, postgresql]
---

Plan and show a compact synchronous Python database integration in your reply. One application uses SQLite locally and PostgreSQL in the cloud. Both existing schemas contain customers(id INTEGER primary key, email TEXT not null unique). Use SQLAlchemy 2.x ORM, sqlite3 locally, and Psycopg 3 for PostgreSQL. We need lookup returning a plain immutable value and updating two customers' emails atomically. The caller should own connection resources and the transaction; cloud credentials must not be logged. Include the key test cases we should run against each backend. No migration, provisioning, retries, or new repository interface is needed.
