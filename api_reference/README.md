# OpenDART API reference

[openapi.yaml](openapi.yaml) is an **unofficial, consumer-maintained OpenAPI 3.2.1 description** of the English OpenDART
API operated by Korea's Financial Supervisory Service (FSS). This repository does not own or operate OpenDART. FSS's
documentation and service behavior take precedence over this reconstruction.

The source is the [English OpenDART site](https://engopendart.fss.or.kr/intro/main.do). The documented server is
`https://engopendart.fss.or.kr/engapi`. This reference does not claim to describe the separate Korean service at
`https://opendart.fss.or.kr/api`; switching hosts is not a supported localization mechanism.

The public guides were retrieved on **2026-10-19**. All **85 services / 167 GET operations** linked from the six
developer indexes are included: 82 services with separate JSON and XML routes, and three ZIP download services. The two
remuneration V2 services are included alongside their earlier versions; the guides do not establish that the earlier
routes are deprecated.

| Official developer index | Services | Operations | Path and schema files |
| --- | ---: | ---: | --- |
| [Disclosure information](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE001) | 4 | 6 | `disclosures.yaml` |
| [Key information from periodic reports](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE002) | 30 | 60 | `periodic-reports.yaml` |
| [Financial information from periodic reports](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE003) | 7 | 13 | `financial-statements.yaml` |
| [Equity disclosure information](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE004) | 2 | 4 | `equity-disclosures.yaml` |
| [Reports on major issues](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE005) | 36 | 72 | `major-issues.yaml` |
| [Securities registration statements](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE006) | 6 | 12 | `securities-registration.yaml` |

## Files and ownership

This directory contains only API documentation, OpenAPI definitions, and source
data. Executable tooling, task recipes, dependency manifests, and build/lint
configuration live in [`../scripts/api_reference/`](../scripts/api_reference/).

- `openapi.yaml`: entry point for documentation, validation, bundling, and code generation. Its `info.version` versions
  this reconstruction; it is not an FSS API version.
- `paths/`: operations grouped by the six official categories. Every operation links to its exact upstream guide and
  retains its official API ID.
- `schemas/`: endpoint-specific response schemas, including each securities-registration section and the nested
  remuneration V2 records. `common.yaml` holds application errors, ZIP bytes, and the unspecified transport-failure
  response.
- `parameters.yaml`: shared query parameters with requiredness, constraints, enums, serialization, public examples, and
  the original `x-upstream-type`.
- `examples.yaml`: three shared, synthetic serialized XML error examples. JSON examples are included with their
  operations.
- `sources/contract-audit-2026-10-20.json`: sanitized live observations for all 167 operations after targeted
  verification of corrected contracts.
- `sources/catalog.json`: the reviewable extraction of all six indexes and 85 endpoint guides, including original field
  descriptions, indentation, container markers, type declarations, code tables, URLs, and hashes of normalized decoded
  HTML. It is the **generation input**, not an authoritative FSS contract. It contains public documentation only.
- [`../tests/contracts/`](../tests/contracts/): Schemathesis live checks, precise operation selection, XML/ZIP
  validation, and offline regression tests. See [CONTRACT_TESTING.md](CONTRACT_TESTING.md).
- [`../scripts/api_reference/`](../scripts/api_reference/): snapshot extraction, deterministic offline generation, and
  offline coverage/schema/example validation. The scripts never load `.env` or API credentials.
- [`../scripts/api_reference/redocly.yaml`](../scripts/api_reference/redocly.yaml): lint configuration; the three
  targeted XML lint exceptions are in [`.redocly.lint-ignore.yaml`](../scripts/api_reference/.redocly.lint-ignore.yaml)
  alongside it.
- [`../scripts/api_reference/build-docs.mjs`](../scripts/api_reference/build-docs.mjs): bundles the specification and
  embeds the pinned Redoc 3
  renderer into the HTML published by GitHub Pages.

Edit [`../scripts/api_reference/build.py`](../scripts/api_reference/build.py) for modeling decisions, or refresh
`sources/catalog.json` for upstream documentation changes, then regenerate. Do not edit generated YAML directly. The
scripts intentionally fail on unknown guide layouts and parameter types rather than silently dropping data.

## Contract decisions

This reference preserves the upstream API's actual route names, query credentials, spelling, suffixes, and
application-level errors. An OpenAPI description cannot retrofit header authentication, resource-style URLs, RFC 9457
problem details, cursor pagination, HTTP error mappings, or rate-limit headers into a service we consume.

- **Authentication:** global `ApiKeyAuth` is an `apiKey` in the query named `crtfc_key`. FSS documents a 40-character
  key. Security Scheme Objects cannot express key length; the scheme description records it. The credential is not
  duplicated as an ordinary parameter, and no usable credential appears in examples.
- **Formats:** `.json` and `.xml` are distinct paths. An `Accept` header is not a replacement for the suffix. JSON
  bodies have no outer `result` property; XML roots are modeled as `result` with repeated, unwrapped `list` and `group`
  elements.
- **Application errors:** success uses string status `000`. Non-success application results share the response
  envelope, including `013` for no data, `020` for quota exhaustion, and `100` for missing or invalid parameters
  (including a missing key). `anyOf` combines success and error schemas; their status constraints are disjoint. Unknown
  future three-digit error codes are accepted. `message` is diagnostic text, not a stable enum.
- **HTTP errors:** `200` describes the normal API exchange, which can contain an application failure. `default`
  documents an unspecified HTTP transport failure without inventing a structured body, HTTP 401/429/503 guarantees, or
  retry headers. The guides do not provide a complete mapping of HTTP statuses to application results. Live checks
  additionally established an HTTP `302` redirect for `/fnlttXbrl.xml` when `rcept_no` is omitted; it has no structured
  error body.
- **Downloads:** `/document.xml`, `/corpCode.xml`, and `/fnlttXbrl.xml` return ZIP bytes on success. XML application
  errors are modeled separately. The corporation directory's XML member has a separate `CorpCodeArchiveMember` schema
  referenced by `x-archive-member-schema`; it is not the HTTP response body and does not require status/message fields.
  OpenAPI extensions may be ignored by generators, so archive extraction remains application code.
- **Types:** identifiers and years are strings. Financial amounts, ratios, and other report scalars remain strings,
  preserving commas, blanks, and `-`. Request pagination is modeled as integers serialized into decimal query values.
  Response pagination counters are modeled as integers. The response tables do not specify scalar JSON types; these are
  consumer modeling decisions checked against bounded authenticated samples; coverage and remaining gaps are recorded in
  [CONTRACT_TESTING.md](CONTRACT_TESTING.md).
- **Response tolerance:** only the application envelope fields are required. Report-specific fields remain optional and
  additional properties are allowed. The guides do not guarantee presence, nullability, or absence conventions. No
  blanket `null` allowance or false precision on amounts/dates has been invented; tighten or broaden individual fields
  only with evidence.
- **Parameter constraints:** dates use eight digits (`YYYYMMDD`), not OpenAPI `format: date`. Patterns check shape, not
  calendar validity or start/end ordering. Report codes, taxonomy variants, disclosure subtypes, financial-index
  categories, sorting, and defaults come from the public guides. Date-range and availability notes remain in
  descriptions where OpenAPI cannot express dependencies between query parameters.
- **Pagination and batching:** disclosure search starts at page 1, defaults to 10 results, and allows up to 100 per
  page. Without `corp_code`, the search interval is limited to three months. `fnlttMultiAcnt` and `fnlttCmpnyIndx`
  accept 1–100 codes through `style: form`, `explode: false`, producing one comma-separated query value.
- **Quota:** the guides mention a usual threshold of 20,000 calls and explicitly permit other configurations. This
  reference does not claim a fixed per-day limit, reset time, requests-per-second limit, or replay policy.
- **Examples:** examples illustrate structure and include synthetic values. They are not captured successful calls or
  evidence that a particular filing exists. They contain no API credentials.
- **Metadata:** FSS's terms are linked. No API license, service SLA, or maintainer support contact has been invented.
  The specification's version and retrieval date are independent.

## Documentation conflicts and remaining uncertainty

The original declarations remain in the source snapshot; the following interpretations are applied explicitly in the
builder:

| Conflict | Consumer interpretation and evidence |
| --- | --- |
| Several periodic-report guides declare `bsns_year` as `STRING(1)` while describing a four-digit fiscal year and showing four-digit form examples. | Four digits; original declaration retained as `x-upstream-type`. |
| [XBRL download](https://engopendart.fss.or.kr/guide/detail.do?apiGrpCd=DE003&apiId=AE00035) declares `rcept_no` as `STRING(8)` but shows a 14-digit filing number and instructs callers to obtain it from disclosure search. | Fourteen digits, consistent with disclosure search and the public example. |
| Both multi-company financial guides declare `corp_code` as `STRING(8)` but their index descriptions and public form examples specify comma-separated company codes; status `021` gives a maximum of 100. | An array of eight-digit strings with CSV query serialization. |
| The [single-company](https://engopendart.fss.or.kr/guide/detail.do?apiGrpCd=DE003&apiId=AE00038) and [multi-company](https://engopendart.fss.or.kr/guide/detail.do?apiGrpCd=DE003&apiId=AE00039) financial-index guides indent all fields after `list` at the root level. | Treat those fields as list-item fields, following the explicit container marker and related financial endpoints. Authenticated JSON/XML samples for 2023 confirmed this nesting on 2026-10-20; the original snapshot is preserved. |
| Financial-index guides say information is available since 2022 but public form examples use 2021. | Preserve the availability note and original example in `x-upstream-example`; use a verified 2023 request example. No unsupported minimum-year constraint. |

Authenticated contract audits now exercise all operations with bounded examples and Schemathesis-generated inputs; see
[the findings and workflow](CONTRACT_TESTING.md). These samples do not establish every optional/null behavior, scalar
variant, or HTTP status mapping. `application/xml` and `text/xml`, and `application/zip` and `application/octet-stream`,
remain compatibility representations. All three download routes additionally document the observed
`application/x-msdownload` header for ZIP bytes.

FSS notes that the data are extracted from submitted disclosures, may be incomplete, and can change with corrected
filings. This reconstruction does not improve or guarantee that source data.

## Rebuild and validate

Use Python 3.10+ for the pinned generation and validation dependencies, in an isolated environment. From the repository
root:

```sh
python3 -m venv .venv-api-reference
.venv-api-reference/bin/python -m pip install -r scripts/api_reference/requirements.txt
.venv-api-reference/bin/python scripts/api_reference/build.py
.venv-api-reference/bin/python scripts/api_reference/check.py
```

`check.py` checks generated-file freshness, OpenAPI 3.2 validity, local reference resolution, exact route/parameter
coverage, response leaf paths and repeated sections, required authentication, unique operation IDs, batch serialization,
application success/error separation, upstream-field tolerance, and every included JSON and parsed XML example. It
explicitly uses `OpenAPIV32SpecValidator`, runs offline, and makes no API calls.

The reference targets [OpenAPI 3.2.1](https://spec.openapis.org/oas/v3.2.1.html)
and explicitly selects the published
[2025-09-17 OpenAPI 3.2 schema dialect](https://spec.openapis.org/oas/3.2/dialect/2025-09-17).
This dialect is bundled by openapi-spec-validator 0.9.0; its offline registry does
not recognize the newer 2026-02-26 dialect URI. Both use JSON Schema Draft 2020-12,
so the existing schema constraints and example validation remain applicable.
Redocly CLI 2.64.1, Redoc CE 3.0.1, and Schemathesis 4.32.0 support this reference
directly, without converting it to an older OpenAPI version. The SDK generator
continues to read the same schema subset, and the HTTP contract is unchanged.

Refresh the public documentation deliberately, then review the snapshot and generated diff:

```sh
python3 scripts/api_reference/snapshot.py
.venv-api-reference/bin/python scripts/api_reference/build.py
.venv-api-reference/bin/python scripts/api_reference/check.py
```

`snapshot.py` makes bounded sequential reads of the six indexes and their linked guides. It only fetches HTTPS guide
index and detail pages on `engopendart.fss.or.kr` and rejects all redirects. `--cache-dir DIRECTORY` can cache public
HTML for interrupted or offline work. Cache filenames must be official guide IDs, and resolved paths must stay inside
the chosen cache directory. Use a fresh directory when checking for upstream changes; an existing cache is reused.
Fetching uses a 60-second timeout per page and does not call the authenticated data API.

With Node.js 22 or newer available, install the locked dependencies and build the
static reference with the Redoc CE and Redocly CLI versions locked in
[`package-lock.json`](../scripts/api_reference/package-lock.json):

```sh
npm --prefix scripts/api_reference ci
npm --prefix scripts/api_reference run lint
mkdir -p site
npm --prefix scripts/api_reference run build
```

CI installs dependencies through Safe Chain with a 48-hour minimum package age.
Regenerate npm lockfiles through Safe Chain so dependency resolution excludes
releases that CI would reject; `npm ci` installs the existing locked versions.

The ignored `site/` directory contains `index.html`, with the specification
and Redoc 3's standalone JavaScript module embedded in the HTML. The page uses
the three-panel layout, supports light and dark modes, and uses hash-based links
that work on GitHub Pages and custom domains. No separate specification file or
external renderer script is needed, and Redoc's telemetry is disabled.

Serve that directory with a local static server to preview it:

```sh
python3 -m http.server 8000 --directory site
```

Open `http://localhost:8000/`. The HTML also works directly from disk.

`build-docs.mjs` uses the CLI only to bundle the source references into a temporary
JSON file, which is deleted after the build. Rendering uses the separately pinned
`redoc` package because this CLI version's `build-docs` command still uses Redoc 2.

Linting and HTML generation were verified with Node.js 22.23.3, Redocly CLI 2.64.1,
and Redoc CE 3.0.1. Python validation used PyYAML 6.0.3,
openapi-spec-validator 0.9.0, and jsonschema 4.26.0. These checks establish internal
consistency and coverage of the retrieved guides, not conformance of the live
upstream service.

The lint exceptions are intentional and narrow:

- `operation-4xx-response` is disabled because the guide does not establish a 4xx contract.
- `info-license` is disabled because no API license has been established.
- The three serialized XML example values are exempted from `no-invalid-media-type-examples`: Redocly 2.64.1 attempts
  to validate XML text as a JSON object. Literal XML strings remain allowed in `value` by
  [OpenAPI 3.2 Example Objects](https://spec.openapis.org/oas/v3.2.1.html#example-object). `check.py` parses them and
  validates their contents separately. Shared reuse means the CLI reports many ignored occurrences of those same three
  values; no JSON examples or other rules are ignored.

## Publish with GitHub Pages

The [reference workflow](../.github/workflows/check-reference.yml) validates generated-file
freshness, coverage, schemas, and examples with `check.py` (which also runs
`build.py --check`), then runs Redocly lint and HTML generation. Python
dependencies come from `uv.lock`; Redocly comes from
[`../scripts/api_reference/package-lock.json`](../scripts/api_reference/package-lock.json)
via `npm ci`. The build reads the checked-in reference and makes no OpenDART API calls.

[CI](../.github/workflows/ci.yml) calls this workflow when the reference, shared
Python dependencies, or relevant CI setup changes; see the
[path rules](../.github/ci-paths.toml). SDK-only and MCP-only changes skip it.
On pull requests, the workflow uploads a `github-pages` artifact containing the
generated HTML for review, retained for seven days. Pull requests do not deploy.
Relevant pushes to `main`, and manual runs on `main`, deploy the same generated
files after the build succeeds. The caller grants Pages write and OIDC permissions
to the reference workflow; within that workflow only the deploy job uses them.
Deployments share a concurrency group and an in-progress deployment is allowed
to finish.

To enable publication:

1. In the GitHub repository, open **Settings → Pages** and select **GitHub Actions**
   as the source.
2. Commit the workflow, reference files, dependency manifests, and lockfiles, then
   merge or push to `main`.
3. Open the **CI** run in **Actions** and expand **API reference**. Its deployment
   links to the published site, normally `https://orestxherija.github.io/opendart/`.
   To rebuild without a new commit, open **CI**, use **Run workflow** with the
   `main` branch, and keep **reference** selected.

Only `site/` is published. Jekyll and a separate hosting service are unnecessary.
A custom domain can be configured in **Settings → Pages**, with the corresponding
DNS records at the domain provider. With Actions publication, a repository
`CNAME` file is not required. Pages hosts the reference; FSS hosts the API.

Renovate checks npm, Python, and action dependencies. Review renderer updates
with the generated output and check navigation, search, color modes, and examples.

Live operation-level contract checks are implemented in the
[contract workflow](../.github/workflows/test-live-contracts.yml). Upstream-guide refresh
automation and semantic compatibility classification are not yet implemented. Refresh into a fresh cache and review the
resulting diff separately
from publication. Formatting and schema lint cannot detect upstream changes;
[oasdiff](https://github.com/oasdiff/oasdiff) is one option for future contract
comparisons.

The relevant tool documentation is [Redocly lint](https://redocly.com/docs/cli/commands/lint),
[bundle](https://redocly.com/docs/cli/commands/bundle),
[Redoc CE's standalone module](https://redocly.com/docs/redoc/deployment/html), and
[GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
