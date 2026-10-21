---
type: llm
---

PASS if the response maps the existing customers table without runtime DDL, chooses the correct drivers, keeps engines caller-owned and sessions per unit, returns a stable plain immutable lookup value, and commits both email changes in one caller-owned transaction with rollback on either failure. PostgreSQL TLS/credentials should be handled safely. It must specify meaningful tests on both real backends, including atomic rollback and expected constraints, and not claim SQLite establishes PostgreSQL behavior. FAIL for internal commits in query helpers, a shared global session, missing cleanup, automatic retries, production schema creation, migration scaffolding, or an imposed repository interface.
