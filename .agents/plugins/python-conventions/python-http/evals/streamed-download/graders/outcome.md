---
type: llm
---

PASS if code uses the existing client's streaming context, checks status before writing body data, iterates bounded chunks, closes the response on all paths, and handles partial output explicitly on failure or cancellation. FAIL if it loads the whole body, creates another client, adds retries, or leaves stream closure to garbage collection.

