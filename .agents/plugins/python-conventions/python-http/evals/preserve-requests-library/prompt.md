---
max_turns: 18
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
tags: [negative, scope]
---

Fix only the missing timeout in this existing requests call. Our project deliberately uses requests; do not migrate libraries or add architecture. Reply with the changed function and a brief explanation.
```python
import requests


def lookup(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.json()
```

