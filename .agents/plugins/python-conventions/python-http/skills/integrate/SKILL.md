---
name: integrate
description: "Integrate an outbound HTTP service into a Python application, selecting the client, adapter, authentication, retry, and testing guidance the requested integration needs. Use for a new upstream or a coordinated integration change."
argument-hint: "<upstream or integration task>"
---

# Integrate an upstream

Inspect the existing HTTP library, settings, resource lifetime, and tests before
choosing components. Preserve the user's scope and existing library. The shipped
references use httpx2; migrating another library requires a migration request.
Apply these steps directly when the host has no agent or shell support.

## Prerequisites

- No mandatory sibling skill or agent. Consult the rows below only as needed.
- Reference implementations target Python 3.11+, httpx2 2.x, and Pydantic 2.x;
  each selected skill states its precise runtime requirements.
- `python-settings` is the declared installation dependency. Consult
  `python-settings:python-settings` when creating or changing root settings,
  environment loading, or settings validation. Reuse an existing settings system.

## Select the required guidance

Identify the requested operations, authentication, upstream semantics, and caller
contract. Explain material unknowns without guessing retry safety or credential
behavior. Load only the skills whose contracts the work changes:

| Work needed | Skill and local fallback |
|---|---|
| Client construction, ownership, timeouts, transport or TLS | `python-http:client` — [client](../client/SKILL.md) |
| API keys, OAuth refresh, mTLS | `python-http:auth` — [auth](../auth/SKILL.md) |
| Retrying a replay-safe operation | `python-http:retries` — [retries](../retries/SKILL.md) |
| Translating failures at an upstream boundary | `python-http:errors` — [errors](../errors/SKILL.md) |
| Typed upstream operations and response parsing | `python-http:api` — [api](../api/SKILL.md) |
| Shared in-flight limits or large fan-out | `python-http:concurrency` — [concurrency](../concurrency/SKILL.md) |
| Uploads, downloads, or streaming response ownership | `python-http:streaming` — [streaming](../streaming/SKILL.md) |
| Request instrumentation, metrics, tracing, or redaction | `python-http:observability` — [observability](../observability/SKILL.md) |
| Testing the changed behavior | `python-http:testing` — [testing](../testing/SKILL.md) |

Implement the smallest complete integration through the existing project seams.
A simple API-key change needs neither OAuth nor a retry policy. Keep timeout,
replay safety, response ownership, and safe logging explicit where relevant.
Read only the selected skill's applicable references; examples illustrate
contracts rather than prescribing the project's layout.

Validate the changed behavior with the project's available checks. Where shell
access exists, the optional [AST checker](../../scripts/check_http.py) can inspect
changed files; pass its absolute path and quote paths containing spaces. Its
findings are advisory and its scope is limited to direct httpx2 calls.

Report the resulting behavior, relevant validation, and any unresolved upstream
contract. Do not claim a test passed unless its command result was observed.
