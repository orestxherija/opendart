---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [negative, preservation, isolation]
---

Keep this small synchronous Python sqlite3 application on the standard library. Please fix only the SQL injection in this function and show the corrected function in your reply. The caller already owns the connection and transaction:

```python
def find_email(connection, email):
    return connection.execute(
        f"SELECT id, email FROM customers WHERE email = '{email}'"
    ).fetchone()
```

Do not introduce SQLAlchemy, an ORM, async, retries, or a new client factory.
