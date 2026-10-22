---
name: review
description: "Review outbound Python HTTP integrations for concrete correctness issues in lifecycle, replay safety, credentials, error handling, concurrency, streaming, and tests. Use when the user requests an HTTP review or audit."
argument-hint: "<files or upstream to review>"
---

# Review an HTTP integration

Review the requested files or upstream. Start from the actual callers, client
construction, response handling, and tests. Preserve the project's HTTP library;
using another library is not itself a defect. Server-side authentication and
route design are outside this outbound-client review.

## Prerequisites and optional tools

No sibling skill, agent, or executable is mandatory. Each concern below links to
its independently useful guidance. The plugin's `python-settings` installation
dependency matters when reviewing settings loading; it is not a prerequisite to
reading HTTP code.

In Claude Code, the optional `python-http:http-reviewer` agent can handle a
substantial read-only review. Give it the target files and requested scope; it
loads skills on demand. Otherwise perform the same review directly. Never
require the agent, hooks, or a shell to complete the core review.

## Follow the relevant contracts

Load a sibling through the Skill tool when available, or read its linked local
file. Select only concerns present in the requested scope:

- [client](../client/SKILL.md) (`python-http:client`): ownership, closure,
  connection pools, explicit timeouts, and TLS.
- [auth](../auth/SKILL.md) (`python-http:auth`): credential placement, token
  refresh, and replay of authenticated requests.
- [retries](../retries/SKILL.md) (`python-http:retries`): upstream idempotency,
  request replay, attempt bounds, deadlines, and retryable failures.
- [errors](../errors/SKILL.md) (`python-http:errors`): actionable translation
  and credential exposure in exception messages, causes, and logs.
- [api](../api/SKILL.md) (`python-http:api`): operation contracts, identifier
  validation, response validation, and caller behavior.
- [concurrency](../concurrency/SKILL.md) (`python-http:concurrency`): shared
  limits, bounded task allocation, queueing, and cancellation.
- [streaming](../streaming/SKILL.md) (`python-http:streaming`): response closure,
  bounded memory, partial files, and upload replayability.
- [observability](../observability/SKILL.md) (`python-http:observability`): safe
  logging, bounded metric labels, and attempt versus operation telemetry.
- [testing](../testing/SKILL.md) (`python-http:testing`): the relevant transport
  seam and tests of observable failures.

If a shell is available, run the [AST checker](../../scripts/check_http.py) on
relevant files as supporting evidence. Resolve its absolute path from this skill
and quote it. Exit 1 means findings; exit 2 means an input could not be checked.
It detects explicit httpx2 constructs only and does not establish overall safety.
The read-only reviewer agent has no shell; its caller can supply checker output.

Report findings by severity with file and line, trigger, consequence, and a
minimal correction. Distinguish demonstrated bugs from unresolved assumptions.
When no concrete defects are found, say so and state any meaningful coverage
limits. Review does not authorize implementation changes or external requests.
