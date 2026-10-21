---
name: review
description: "Review Python database clients for concrete lifecycle, transaction, ORM loading, query safety, retry, streaming, and diagnostic defects. Use for a requested database review or audit; preserve the existing driver and do not mutate schema."
---

# Review a database integration

Review supplied scope, starting with callers, engine/session creation,
transactions, SQL, results, and tests. An existing driver or synchronous code is
not itself a defect. Administration and migration design are outside this review.

## Optional tools

No agent, shell, connection, or sibling skill is mandatory. Where supported,
`python-db:db-reviewer` performs the same read-only workflow. Supply files/scope,
not an unspecified whole-repository audit. Start with code/existing test evidence.

## Follow relevant contracts

Read only guidance for concerns actually present:

- [client](../client/SKILL.md): engine lifetime, pools, disposal, TLS.
- [transactions](../transactions/SKILL.md): atomicity, rollback, isolation,
  task-shared sessions, cancellation cleanup.
- [orm](../orm/SKILL.md): identity, implicit I/O, detached objects, loading.
- [queries](../queries/SKILL.md): binding, identifiers, cardinality, lost updates.
- [errors](../errors/SKILL.md): classification and safe translation.
- [retries](../retries/SKILL.md): complete replay, effects, bounds, unknown commits.
- [performance](../performance/SKILL.md): demonstrated query/pool bottlenecks.
- [bulk](../bulk/SKILL.md): bounds, cursor ownership, partial output.
- [observability](../observability/SKILL.md): secrets and unbounded labels.
- [testing](../testing/SKILL.md): backend coverage and meaningful failures.

Report findings by severity with file/line, trigger, consequence, evidence, and
a minimal correction. Separate demonstrated defects from schema/deployment
assumptions. Say when no concrete findings were found and identify meaningful
coverage limits. Do not turn review into unsolicited driver migration,
restructuring, or schema changes. Review alone does not authorize code changes
or connections to external databases.
