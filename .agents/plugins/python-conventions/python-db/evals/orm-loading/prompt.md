---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [activation, orm, isolation]
---

Our async SQLAlchemy 2.x service already owns its engine and creates a session per operation. Customer.orders is a mapped collection with the default lazy loader. This lookup sometimes raises MissingGreenlet, and a sync version makes one extra query per customer:

```python
async def summaries(factory):
    async with factory() as session:
        customers = (await session.scalars(select(Customer))).all()
        return [{"id": c.id, "order_ids": [o.id for o in c.orders]} for c in customers]
```

The Customer and Order mappings already exist. Return a focused correction with predictable relationship loading and a short explanation. Do not rebuild the client or redesign our model layer.
