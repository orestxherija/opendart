# Live contract testing

The harness and offline regressions live in [`../tests/contracts/`](../tests/contracts/).
The `contracts` dependency group pins Schemathesis 4.32.0 in `uv.lock`. The runner
uses its Python API to generate requests and check HTTP status and media-type
conformance. JSON Schema checks also validate JSON bodies, parsed XML, and the
corporation-directory XML inside ZIP downloads. ZIP responses are checked for
structure and CRC integrity without extracting files.

These are real, authenticated GET requests to FSS's **English** OpenDART service.
An application error can be a valid contract result; it does not establish that
the corresponding success payload was verified. Reports distinguish those cases.

## Run locally

From the repository root, install the isolated test dependencies using the
repository's Safe Chain setup:

```sh
uv sync --locked --only-group contracts --only-group dev
uv run --no-sync pytest tests/contracts -o addopts=''
```

Set `OPENDART_API__API_KEY` to an issued key. The legacy `OPENDART_API_KEY` name is
also accepted. To load the existing ignored `.env` explicitly and audit all 167
operations:

```sh
uv run --no-sync --env-file .env python -m tests.contracts.run
```

To reproduce one operation or change the deterministic seed:

```sh
uv run --no-sync --env-file .env python -m tests.contracts.run \
  --operation 'GET /company.json' --seed 20261020 --examples 2
```

Each operation gets its public parameter examples, a missing-key request, an
omission of its first required data parameter when one exists, and up to two
Schemathesis-generated requests. Generated values satisfy the OpenAPI input
shape, but may address nonexistent filings or violate cross-field rules that
OpenAPI cannot express. The parameterless corporation download is tested once
with credentials and once without; it has no data input to fuzz.

The audit is sequential, starts requests at least 0.5 seconds apart, and caps
actual requests at `selected operations × (examples + 3)`. Requests have a
20-second network timeout; streamed reads additionally check a five-minute
response deadline and a 25 MiB response limit. The run has a 25-minute budget,
and the CI job has a 30-minute timeout. ZIP expansion is limited to 100 MiB.
Slow or oversized responses fail visibly; these are test limits, not claims
about FSS's contract. Redirects are not followed, and credentials can only be
sent to `https://engopendart.fss.or.kr/engapi/`.

Hypothesis shrinking, database replay, and failure reproduction requests are
disabled. Transport-level resend attempts are included in the request budget.
Credential rejection, quota exhaustion, and service failures stop further
operations and fail the audit. Undocumented HTTP statuses and server errors fail
even though the reference has a `default` transport-failure response. Explicit
documented errors, including the XBRL redirect, are checked without following them.

## Select changed operations

```sh
uv run --no-sync python -m tests.contracts.selection \
  --base FULL_BEFORE_COMMIT_SHA --head FULL_AFTER_COMMIT_SHA \
  --output contract-results/selection.json
uv run --no-sync --env-file .env python -m tests.contracts.run \
  --selection contract-results/selection.json
```

The selector resolves local references **at both revisions** and compares
operations by HTTP method and path. It includes transitive response schemas,
examples, inherited parameters, servers, and the security schemes actually used
by the operation. A shared response or parameter edit therefore selects only its
consumers. Changing global security or servers selects affected inheriting
operations. Changing OpenAPI version or the default schema dialect affects every
operation. Changes to unused components, YAML formatting, root metadata, or
reference presentation do not produce API calls. Operation descriptions and
examples do count as operation changes.

New operations are tested; removed operations are reported without being called.
An initial reference or all-zero Git before SHA selects all current operations.
Missing history, broken references, and unsupported reference cycles fail
selection rather than silently skipping checks. Only local JSON Pointer
references within `api_reference` are supported by this reference's selector.

## GitHub Actions

[Live API contracts](../.github/workflows/contracts.yml) runs after a push or merge
to the repository's configured default branch when generated OpenAPI files have
changed. It compares `github.event.before` with `github.sha`, covering the entire
push rather than just the last commit. Feature branches and pull requests never
make authenticated calls. Separate pushes retain their own runs and selections.
**Run workflow** on the default branch performs a full audit.

Configure the repository's **Actions secret `OPENDART_API_KEY`** with a key valid
for the English service. If FSS restricts its allowed IP addresses, the runner's
egress address must be permitted. A selected audit fails clearly when the secret
is missing. An empty selection exits successfully without needing a key.

The existing API reference workflow runs the selector and validator's regression
tests offline on relevant pull requests. It builds Redoc from the generated spec;
the live workflow does not automatically rewrite or publish unreviewed findings.

## Review findings and update Redoc

`contract-results/report.json` records the selected operations, generated query
inputs, seed, media types, HTTP/application statuses, body hashes, and schema
failure locations. It saves progress after each operation and lists operations
whose success response was not observed. Keys, credential-bearing URLs, raw
response bodies, exception text, and curl reproductions are excluded. Reports
are ignored locally and uploaded with the selection as a 14-day Actions artifact,
including failed runs. A Markdown summary is also attached to the Actions run.
In these reports, `ZIP` denotes a validated archive, not a literal API status code.

For each mismatch, reproduce the affected operation and distinguish a reference
error from an upstream outage or insufficient example data. Add an offline
regression where useful, correct `scripts/api_reference/build.py` or the reviewed source
catalog, and regenerate:

```sh
uv run --no-sync python scripts/api_reference/build.py
uv run --no-sync python scripts/api_reference/check.py
uv run --no-sync python scripts/generate_sdk.py --check
npm --prefix api_reference run lint
npm --prefix api_reference run build
```

Redoc receives the corrected media types, schemas, descriptions, and error
examples through the same generated OpenAPI document. Never invent HTTP 401 or
429 responses from application status codes, or loosen schemas simply to hide
a failed test. A successful bounded run does not cover every filing, historical
variant, optional field, or possible generated input.

## Initial observations

The [reviewed audit summary](sources/contract-audit-2026-10-20.json) covers all
**167 operations**, with a validated success response observed for every operation
and **zero remaining mismatches** after the corrections below. The initial runs
used one generated case per operation with data parameters. Eight affected
operations were rerun with two generated cases each: **40 requests, all passing**.
This is bounded sample coverage, not proof that every filing or optional field
has the same shape. Full sanitized reports are retained locally in the ignored
`contract-results/` directory; CI retains its own reports as artifacts.

The authenticated audit on 2026-10-20 confirmed JSON/XML application envelopes
and found that a missing `crtfc_key` produces an HTTP 200 application error with
status `100`. The reference now describes missing as well as invalid parameters
and includes this error example for JSON, XML, and download routes. The examples
remain synthetic; upstream message wording is not treated as a stable enum.

`/corpCode.xml`, `/document.xml`, and `/fnlttXbrl.xml` returned ZIP bytes with
`Content-Type: application/x-msdownload;charset=UTF-8`. That observed media type
is now included on those observed download operations, alongside
the existing compatibility representations. ZIP structure and CRC checks passed
for all three; the corporation directory's XML member also passed its schema.
The document and XBRL archives have no member schemas in this reference.

Omitting `rcept_no` on `/fnlttXbrl.xml` returned **HTTP 302** to `/error.html`,
without a body or `Content-Type`. The spec now includes that response and its
`Location` header. This redirect is an error path, not a successful ZIP or an
application-status envelope; the runner does not follow it.

The public financial-index examples use fiscal year **2021**, before the guides'
stated 2022 availability, and returned `013`. Examples now use corporation
`00126380`, fiscal year **2023**, annual report `11011`, and category `M210000`.
Both single-company and multi-company routes returned valid JSON/XML success
responses with `list` records, confirming the previously inferred nesting for
these samples. Original examples remain in `x-upstream-example` and the catalog.
