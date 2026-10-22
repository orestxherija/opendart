---
name: observability
description: "Instrument Python database clients with safe operation timings, pool and transaction diagnostics, and bounded labels. Use for database logs, metrics, or tracing without leaking SQL parameters, connection strings, or error messages."
---

# Safe database diagnostics

Measure without disclosing values or turning user input into metric labels.
Distinguish complete operations, retry attempts, SQL execution, and pool waiting.

## Prerequisites and reference

Python 3.11+; no telemetry vendor or sibling module is required.
[example.py](references/example.py) exposes
`observe_operation(operation_name, emit)` and
`OperationMetric(name, duration_seconds, outcome)`. Use an application-defined
name and wrap the whole unit, including commit. The ordinary `with` context also
works around awaited operations. It emits no SQL, parameters, or exception text.

## Select useful signals

- Keep operation names/categories bounded. Whole-operation timing includes the
  caller's work inside the context; SQL execution and pool waiting need separate
  instrumentation when diagnosing those phases.
- Track pool waiting/saturation, long transactions, retries, and connection
  failures when useful. State whether a metric counts attempts or operations.
- Omit arbitrary SQL, values, rows, DSNs, and raw driver messages from general
  telemetry. Hashing arbitrary SQL does not bound label cardinality. Avoid
  `echo=True` as production logging.
- Tracebacks can expose SQL/parameters even if an outer message is safe. Use
  structured [error categories](../errors/SKILL.md) at reporting boundaries.
- Instrumentation must not replace query results/errors. Keep callbacks cheap
  and prevent their failures from breaking database work.

If OpenTelemetry is already present, reuse its provider and inspect statement
and parameter collection settings. Do not add a tracing backend for basic
operation timings. Test success, failure, and absence of sentinel secrets.
