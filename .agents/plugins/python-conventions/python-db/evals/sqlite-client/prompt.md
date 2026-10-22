---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, sqlite, isolation]
---

I have a synchronous Python 3.11 command-line tool that connects to a local SQLite file through SQLAlchemy 2.x. Give me a small engine factory and an entry-point example in your reply. Keep foreign keys enforced on every connection, use predictable transaction behavior on Python 3.11, bound lock waiting, and dispose the engine. The database already exists. Do not add async, schema creation, migrations, or WAL configuration.
