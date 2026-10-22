---
name: errors
description: "Classify and translate Python database failures using SQLSTATE or SQLite result codes while keeping secrets out of diagnostics. Use for database boundary error contracts, not deciding transaction replay by itself."
---

# Database failure classification

Classify structured driver information. Error text varies, can contain SQL and
values, and is not a reliable retry signal.

## Prerequisites and reference

Python 3.11+ and SQLAlchemy 2.x. [example.py](references/example.py) exposes
`classify_error(error, backend=...) -> Failure` with `kind`, `code`, and
`retry_transaction`. It handles SQLAlchemy wrappers and structured underlying
errors. No database connection is needed to classify a captured exception.

Keep unknown errors unknown. PostgreSQL exposes SQLSTATE; SQLite exposes result
codes on supported Python exceptions. An eligible category is an input to
[retries](../retries/SKILL.md), not authorization to replay.

Translate expected failures only when callers have a useful action. One known
uniqueness constraint may mean a conflict, but all `IntegrityError` instances do
not mean duplicate email. Classify before producing a safe public exception.

Avoid `str(exc)`, parameters, full DSNs, and chained database tracebacks at public
boundaries. A safe outer message does not sanitize its cause. Record bounded
codes/categories and an application-owned operation name through
[observability](../observability/SKILL.md).

Validate real driver failures and unknown exceptions. Do not retry programming
errors, generic integrity failures, or arbitrary connection loss. Disconnects
during commit can leave the result unknown.
