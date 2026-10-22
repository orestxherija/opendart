---
name: observability
description: Add safe outbound HTTP diagnostics, metrics, and tracing while separating logical operations from attempts and excluding sensitive request data.
---

# HTTP observability

Instrument the question the application needs to answer: operation success,
attempt counts, queueing, time to headers, or complete body consumption. Label
metrics with static upstream and operation names. URLs, path identifiers,
query strings, credentials, payloads, and arbitrary exception messages can leak
secrets and create unbounded metric cardinality.

## Prerequisites and routing

- The reference requires Python 3.11+ and `httpx2>=2.13,<3`. It imports no
  settings, exception hierarchy, metrics vendor, or sibling references.
- Read [the diagnostics and observation reference](references/example.py) for
  `log_failure`, `safe_failure_fields`, and `observe_call`.
- Consult [python-http:errors](../errors/SKILL.md) when changing public failure
  categories, [python-http:retries](../retries/SKILL.md) when distinguishing an
  attempt from a retry sequence, and
  [python-http:streaming](../streaming/SKILL.md) when timing body consumption.

## Keep operational logs safe

Preserve the original exception as a cause for debugging. At the operational
logging boundary, emit allowlisted fields and omit `exc_info`, `stack_info`,
exception interpolation, and traceback formatting. A safe outer exception
message does not sanitize its chained `httpx2.HTTPStatusError`, Pydantic input
values, suppressed context, or an exception group's children. The reference
never formats any of those values; it emits exception class names and a numeric
HTTP status when available. Pass trusted, static labels such as `billing` and
`fetch_invoice`, never a URL or user-supplied identifier.

This protects records produced by the helper. Review framework exception
handlers, request middleware, SDK exporters, and httpx2/httpcore debug logging
separately because they may still emit raw requests or tracebacks. Where raw
debugging is necessary, use the application's restricted diagnostic channel and
retention policy rather than assuming a generic text-redaction regex is enough.

## Count the intended operation

Wrap the whole operation, including retries, once for user-facing latency and
success metrics. Add `layer="attempt"` observations inside the retry callable
only if attempt-level metrics are needed. Do not add both layers to the same
counter. The reference accepts a small nonblocking metrics callback instead of
imposing a metrics backend; adapt it to the application's existing system.

HTTP response hooks run before the body is consumed and do not see every
transport exception. They are suitable for time-to-headers measurements, not
complete transfer duration or universal failure counts. To measure a complete
transfer, wrap the function that consumes and closes its response. Include
limiter acquisition inside the observation when queueing belongs in latency;
measure it separately when diagnosing saturation.

If tracing already exists, extend it without adding duplicate client spans.
Use the existing propagator, restrict propagation to intended destinations, and
verify exporter defaults: automatic URL attributes and exception events can
reintroduce sensitive data even when application logs are sanitized.
