# python-http

Tested outbound HTTP conventions for Python 3.11+ using `httpx2>=2.13,<3`.
Version **0.3.0**. Declares `python-settings` `^1.0` as an installation dependency;
only examples that use settings need its Python contracts.

## Install and use

After adding this marketplace, install in Claude Code:

```text
/plugin install python-http@python-conventions
```

Ask for the work naturally or invoke a skill directly, for example
`/python-http:review src/billing.py` or `/python-http:integrate billing`.
Existing clients and libraries are valid starting points; the plugin does not
require an unsolicited library migration or new factory.

## Choose the skill for the task

| Skill | Owns | Minimal reference prerequisites |
|---|---|---|
| [client](skills/client/SKILL.md) | Construction, ownership, pools, timeouts, TLS | Shipped settings group/types |
| [auth](skills/auth/SKILL.md) | API keys, OAuth2 refresh, mTLS | Settings for the selected scheme; caller-owned client |
| [retries](skills/retries/SKILL.md) | Replay safety, attempts, backoff, deadlines | Shipped settings group/types |
| [errors](skills/errors/SKILL.md) | Failure classification and translation | httpx2 and Pydantic |
| [api](skills/api/SKILL.md) | Typed upstream methods, validation, safe paths | Errors reference; existing client |
| [testing](skills/testing/SKILL.md) | Transport tests, network guard, business fakes | pytest and httpx2; no application imports in the basic example |
| [concurrency](skills/concurrency/SKILL.md) | Bounded workers, shared limits, queueing deadlines | Standard library only |
| [streaming](skills/streaming/SKILL.md) | Bounded transfers, ownership, cancellation | httpx2; existing client |
| [observability](skills/observability/SKILL.md) | Safe diagnostics and operation/attempt metrics | httpx2; no vendor or sibling modules |
| [integrate](skills/integrate/SKILL.md) | Select components for an upstream integration | Selected guidance only |
| [review](skills/review/SKILL.md) | Inspect an integration and report concrete defects | Selected guidance only |

Each skill is independently readable and links additional guidance where needed.
A simple API-key change loads its small reference; it does not require OAuth,
retries, or an API adapter. Typed adapters send once by default; retry composition
and bulk endpoints have separate examples. Basic transport tests import no
application modules; advanced fixtures explicitly state their dependencies.

The [reference registry](reference-project.json) records every example's suggested
module name and direct prerequisites. The [settings contract](references/settings-contract.md)
ships the minimal settings adapters and explains how to reuse existing ones.
Install Python libraries in the consuming project separately.

## Optional automation

The [reviewer agent](agents/http-reviewer.md) provides a focused read-only review
when the host supports agents. The review skill describes the same workflow for
hosts without them. It has no shell or write tools and loads relevant skills on
demand.

The [AST checker](scripts/README.md) reports three explicit httpx2 constructs:
disabled TLS verification, disabled timeouts, and clients created at import time.
It is a narrow advisory tool; inspect context before treating a finding as a bug.
The edit hook runs that checker only after a project enables
[its configuration](hooks/config.example.toml). It makes no model calls and
cannot block or undo an edit. Python must be available on the host.

The [behavioral eval cases](evals/README.md) exercise skill selection, scope, and
composed outcomes. They complement executable reference tests. Paid evaluations
are opt-in; authored cases are not evidence of passing model behavior.

## Migrating from 0.2

- `HttpClientSettings.max_concurrent` and `gather_bounded` leave the client
  reference. Remove the old settings field and pass an explicit operation limit
  to `map_bounded(items, operation, limit=...)` in `app.http_concurrency`.
  Share a semaphore where multiple callers need one upstream budget.
- API-key auth stays in `app.http_auth`; OAuth2 moves to `app.http_oauth2` and
  mTLS to `app.http_mtls`. Copy only the scheme being used and update imports.
- OAuth2 defaults to `replay_after_401=False`: a rejected token is invalidated,
  but the failed operation returns its 401 without automatic body buffering or
  replay. Opt into `True` only for replay-safe operations with known small bodies.
- `BillingApi(client, *, sender=None)` no longer requires a retry policy. It
  sends once unless the caller injects a sender. The
  [retry composition example](skills/api/references/with_retries.py) demonstrates
  `partial(send_with_retries, policy=policy)` for a replay-safe operation.
- Bulk billing behavior moves to `app.billing_bulk`; retry composition moves to
  `app.billing_retries`. OAuth, retry, billing, and ASGI test examples are separate
  files under the testing skill. Update copied imports as needed.
- Identifiers that are empty or complete dot segments are rejected before a
  request. Safe outer exception text still requires safe logging at the boundary;
  the observability reference omits secret-bearing messages and chained tracebacks.

## Boundaries

These skills cover outbound HTTP clients. Server routing, inbound authentication,
and framework architecture belong to the consuming application's conventions.
Rate limiting, circuit breakers, provider-specific pagination, resumable transfers,
and DNS resolvers remain integration-specific decisions. Add a separate skill
when a concrete recurring task justifies its state and operational contract.
