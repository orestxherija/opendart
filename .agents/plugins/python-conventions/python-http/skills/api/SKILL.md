---
name: api
description: "Build or review typed Python adapters for an outbound HTTP upstream: domain methods, request/response models, safe identifiers, and caller-facing failures. Applies to upstream clients, not server routes."
metadata:
  author: Orest Xherija
  category: python
---

# Typed upstream adapters

Wrap an existing client when endpoint details, response shapes, or failure
handling need a stable boundary. Preserve a simple existing function when it
already owns that boundary; do not introduce an adapter merely for a one-line
client configuration change.

## Prerequisites

Python 3.11+, `httpx2>=2.13,<3`, `pydantic>=2.7,<3`.
The minimal [billing reference](references/example.py), project module
`app.billing_api`, uses the exception types and translator from
[errors](../errors/SKILL.md) as `app.http_errors`. Reuse matching project
exceptions or load that reference when the boundary does not exist yet.

The caller supplies an `httpx2.AsyncClient` and owns its lifetime. A factory,
authentication flow, settings package, and retry helper are optional
composition choices, not prerequisites for the minimal adapter.

## Define the boundary

1. Methods take domain arguments and return typed models. Keep raw responses,
   status codes, and transport exceptions inside the boundary.
2. Model only response fields the application uses, with `extra="ignore"`.
   Validate required fields; tolerate unrelated fields the upstream adds.
3. Use request models with `extra="forbid"` and serialize using
   `model_dump(mode="json")`.
4. Validate identifiers against the upstream's documented syntax. Reject empty
   identifiers and complete "."/".." segments before escaping path segments.
   `quote(value, safe="")` leaves dots unchanged; escaping alone does not
   establish endpoint confinement. Pass query values with `params=`.
5. Map expected statuses before general error translation. Check status before
   validating response bytes with `model_validate_json(response.content)`.
6. Add retries only to operations the upstream permits replaying. The minimal
   adapter sends once; an optional `sender` callable supplies retry composition.
   Keep one idempotency key per logical create only when the provider supports
   it. Durable callers must preserve that identity across job retries.
7. Keep authorization, redirects, deadlines, and request-body replay tied to the
   specific endpoint's contract.

## Load specialized examples only when needed

- [with_retries.py](references/with_retries.py), module `app.billing_retries`:
  opt-in retry composition using `partial(send_with_retries, policy=policy)`;
  depends on the minimal adapter and `app.http_retries`.
- [bulk.py](references/bulk.py), module `app.billing_bulk`: bulk lookup with
  deduplication and documented chunk limits; depends on the minimal adapter.
  Missing results are absent only because this billing example defines that
  behavior. Adapt partial failures to the actual provider contract.
- Pagination: follow the provider's cursor/link contract; bound pages or items,
  detect repeated cursors, and verify the origin of supplied next-page URLs
  before sending credentials. Fetch pages incrementally.
- [concurrency](../concurrency/SKILL.md): parallelizing independent requests or
  bulk chunks with bounded work.
- [streaming](../streaming/SKILL.md): methods that intentionally expose a stream
  need an explicit ownership/closure contract beyond a returned JSON model.

Consult [client](../client/SKILL.md) only when construction or lifetime changes,
[auth](../auth/SKILL.md) for credentials, [retries](../retries/SKILL.md) for retry
policy, and [testing](../testing/SKILL.md) for transport tests or business fakes.
