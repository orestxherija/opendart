---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [negative, scope]
---

We are deciding which tooling area owns a future PostgreSQL schema migration: renaming an existing column across staged deployments and generating Alembic revisions. This request is only for a short scope explanation, not implementation. Does a client-side database plugin own this? Explain what belongs to migration tooling and what remains with the database client. Do not write code or inspect a project.
