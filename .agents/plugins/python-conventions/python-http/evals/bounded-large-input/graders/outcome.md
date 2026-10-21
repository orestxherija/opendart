---
type: llm
---

PASS if the design bounds task allocation and queued work independently of input size, uses a shared upstream limit across batches, maintains input order without collecting all input eagerly, and closes/cancels workers when the caller stops. FAIL if it wraps asyncio.gather over every ID with only a semaphore or allocates all ten million tasks.

