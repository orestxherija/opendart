# OpenDART API reference

[openapi.yaml](openapi.yaml) is an **unofficial, consumer-maintained OpenAPI 3.1.0 description** of the English OpenDART API operated by Korea's Financial Supervisory Service (FSS). This repository does not own or operate OpenDART. FSS's documentation and service behavior take precedence over this reconstruction.

The source is the [English OpenDART site](https://engopendart.fss.or.kr/intro/main.do). The documented server is `https://engopendart.fss.or.kr/engapi`. This reference does not claim to describe the separate Korean service at `https://opendart.fss.or.kr/api`; switching hosts is not a supported localization mechanism.

The public guides were retrieved on **2026-10-19**. All **85 services / 167 GET operations** linked from the six developer indexes are included: 82 services with separate JSON and XML routes, and three ZIP download services. The two remuneration V2 services are included alongside their earlier versions; the guides do not establish that the earlier routes are deprecated.

| Official developer index | Services | Operations | Path and schema files |
| --- | ---: | ---: | --- |
| [Disclosure information](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE001) | 4 | 6 | `disclosures.yaml` |
| [Key information from periodic reports](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE002) | 30 | 60 | `periodic-reports.yaml` |
| [Financial information from periodic reports](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE003) | 7 | 13 | `financial-statements.yaml` |
| [Equity disclosure information](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE004) | 2 | 4 | `equity-disclosures.yaml` |
| [Reports on major issues](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE005) | 36 | 72 | `major-issues.yaml` |
| [Securities registration statements](https://engopendart.fss.or.kr/guide/main.do?apiGrpCd=DE006) | 6 | 12 | `securities-registration.yaml` |

## Files and ownership

- `openapi.yaml`: entry point for documentation, validation, bundling, and code generation. Its `info.version` versions this reconstruction; it is not an FSS API version.
- `paths/`: operations grouped by the six official categories. Every operation links to its exact upstream guide and retains its official API ID.
- `schemas/`: endpoint-specific response schemas, including each securities-registration section and the nested remuneration V2 records. `common.yaml` holds application errors, ZIP bytes, and the unspecified transport-failure response.
- `parameters.yaml`: shared query parameters with requiredness, constraints, enums, serialization, public examples, and the original `x-upstream-type`.
- `examples.yaml`: two shared, synthetic serialized XML error examples. JSON examples are included with their operations.
- `sources/catalog.json`: the reviewable extraction of all six indexes and 85 endpoint guides, including original field descriptions, indentation, container markers, type declarations, code tables, URLs, and hashes of normalized decoded HTML. It is the **generation input**, not an authoritative FSS contract. It contains public documentation only.
- `scripts/`: snapshot extraction, deterministic offline generation, and offline coverage/schema/example validation. The scripts never load `.env` or API credentials.
- `redocly.yaml`: lint configuration; the two targeted XML lint exceptions are in `.redocly.lint-ignore.yaml`.
- `scripts/build-docs.mjs`: bundles the specification and embeds the pinned Redoc 3
  renderer into the HTML published by GitHub Pages.

Edit `scripts/build.py` for modeling decisions, or refresh `sources/catalog.json` for upstream documentation changes, then regenerate. Do not edit generated YAML directly. The scripts intentionally fail on unknown guide layouts and parameter types rather than silently dropping data.

## Contract decisions

This reference preserves the upstream API's actual route names, query credentials, spelling, suffixes, and application-level errors. An OpenAPI description cannot retrofit header authentication, resource-style URLs, RFC 9457 problem details, cursor pagination, HTTP error mappings, or rate-limit headers into a service we consume.

- **Authentication:** global `ApiKeyAuth` is an `apiKey` in the query named `crtfc_key`. FSS documents a 40-character key. Security Scheme Objects cannot express key length; the scheme description records it. The credential is not duplicated as an ordinary parameter, and no usable credential appears in examples.
- **Formats:** `.json` and `.xml` are distinct paths. An `Accept` header is not a replacement for the suffix. JSON bodies have no outer `result` property; XML roots are modeled as `result` with repeated, unwrapped `list` and `group` elements.
- **Application errors:** success uses string status `000`. Non-success application results share the response envelope, including `013` for no data and `020` for quota exhaustion. `anyOf` combines success and error schemas; their status constraints are disjoint. Unknown future three-digit error codes are accepted. `message` is diagnostic text, not a stable enum.
- **HTTP errors:** `200` describes the normal API exchange, which can contain an application failure. `default` documents an unspecified HTTP transport failure without inventing a structured body, HTTP 401/429/503 guarantees, or retry headers. The guides do not provide a complete mapping of HTTP statuses to application results.
- **Downloads:** `/document.xml`, `/corpCode.xml`, and `/fnlttXbrl.xml` return ZIP bytes on success. XML application errors are modeled separately. The corporation directory's XML member has a separate `CorpCodeArchiveMember` schema referenced by `x-archive-member-schema`; it is not the HTTP response body and does not require status/message fields. OpenAPI extensions may be ignored by generators, so archive extraction remains application code.
- **Types:** identifiers and years are strings. Financial amounts, ratios, and other report scalars remain strings, preserving commas, blanks, and `-`. Request pagination is modeled as integers serialized into decimal query values. Response pagination counters are modeled as integers. The response tables do not specify scalar JSON types; these are explicit consumer modeling assumptions, pending verification against authenticated responses.
- **Response tolerance:** only the application envelope fields are required. Report-specific fields remain optional and additional properties are allowed. The guides do not guarantee presence, nullability, or absence conventions. No blanket `null` allowance or false precision on amounts/dates has been invented; tighten or broaden individual fields only with evidence.
- **Parameter constraints:** dates use eight digits (`YYYYMMDD`), not OpenAPI `format: date`. Patterns check shape, not calendar validity or start/end ordering. Report codes, taxonomy variants, disclosure subtypes, financial-index categories, sorting, and defaults come from the public guides. Date-range and availability notes remain in descriptions where OpenAPI cannot express dependencies between query parameters.
- **Pagination and batching:** disclosure search starts at page 1, defaults to 10 results, and allows up to 100 per page. Without `corp_code`, the search interval is limited to three months. `fnlttMultiAcnt` and `fnlttCmpnyIndx` accept 1–100 codes through `style: form`, `explode: false`, producing one comma-separated query value.
- **Quota:** the guides mention a usual threshold of 20,000 calls and explicitly permit other configurations. This reference does not claim a fixed per-day limit, reset time, requests-per-second limit, or replay policy.
- **Examples:** examples illustrate structure and include synthetic values. They are not captured successful calls or evidence that a particular filing exists. They contain no API credentials.
- **Metadata:** FSS's terms are linked. No API license, service SLA, or maintainer support contact has been invented. The specification's version and retrieval date are independent.

## Documentation conflicts and remaining uncertainty

The original declarations remain in the source snapshot; the following interpretations are applied explicitly in the builder:

| Conflict | Consumer interpretation and evidence |
| --- | --- |
| Several periodic-report guides declare `bsns_year` as `STRING(1)` while describing a four-digit fiscal year and showing four-digit form examples. | Four digits; original declaration retained as `x-upstream-type`. |
| [XBRL download](https://engopendart.fss.or.kr/guide/detail.do?apiGrpCd=DE003&apiId=AE00035) declares `rcept_no` as `STRING(8)` but shows a 14-digit filing number and instructs callers to obtain it from disclosure search. | Fourteen digits, consistent with disclosure search and the public example. |
| Both multi-company financial guides declare `corp_code` as `STRING(8)` but their index descriptions and public form examples specify comma-separated company codes; status `021` gives a maximum of 100. | An array of eight-digit strings with CSV query serialization. |
| The [single-company](https://engopendart.fss.or.kr/guide/detail.do?apiGrpCd=DE003&apiId=AE00038) and [multi-company](https://engopendart.fss.or.kr/guide/detail.do?apiGrpCd=DE003&apiId=AE00039) financial-index guides indent all fields after `list` at the root level. | Treat those fields as list-item fields, following the explicit container marker and related financial endpoints. This is an inference, not an upstream correction. |
| Financial-index guides say information is available since 2022 but public form examples use 2021. | Preserve the availability note and original example; no unsupported minimum-year constraint. |

No authenticated success calls were made. Full scalar typing, optional/null behavior, media-type headers, XML serialization details, HTTP status mappings, and the inferred financial-index nesting still need verification against permitted real responses. `application/xml` and `text/xml`, and `application/zip` and `application/octet-stream`, are compatibility representations; the guides identify XML/ZIP formats without guaranteeing the corresponding headers.

FSS notes that the data are extracted from submitted disclosures, may be incomplete, and can change with corrected filings. This reconstruction does not improve or guarantee that source data.

## Rebuild and validate

Use Python 3.10+ for the pinned generation and validation dependencies, in an isolated environment. From the repository root:

```sh
python3 -m venv .venv-api-reference
.venv-api-reference/bin/python -m pip install -r api_reference/requirements.txt
.venv-api-reference/bin/python api_reference/scripts/build.py
.venv-api-reference/bin/python api_reference/scripts/check.py
```

`check.py` checks generated-file freshness, OpenAPI 3.1 validity, local reference resolution, exact route/parameter coverage, response leaf paths and repeated sections, required authentication, unique operation IDs, batch serialization, application success/error separation, upstream-field tolerance, and every included JSON and parsed XML example. It runs offline and makes no API calls.

Refresh the public documentation deliberately, then review the snapshot and generated diff:

```sh
python3 api_reference/scripts/snapshot.py
.venv-api-reference/bin/python api_reference/scripts/build.py
.venv-api-reference/bin/python api_reference/scripts/check.py
```

`snapshot.py` makes bounded sequential reads of the six indexes and their linked guides. `--cache-dir DIRECTORY` can cache public HTML for interrupted or offline work. Use a fresh directory when checking for upstream changes; an existing cache is reused. Fetching uses a 60-second timeout per page and does not call the authenticated data API.

With Node.js **22.23.3** available, install the locked dependencies and build the
static reference using **Redoc CE 3.0.1** and **Redocly CLI 2.64.1**:

```sh
npm --prefix api_reference ci
npm --prefix api_reference run lint
mkdir -p site
npm --prefix api_reference run build
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
openapi-spec-validator 0.7.2, and jsonschema 4.26.0. These checks establish internal
consistency and coverage of the retrieved guides, not conformance of the live
upstream service.

The lint exceptions are intentional and narrow:

- `operation-4xx-response` is disabled because the guide does not establish a 4xx contract.
- `info-license` is disabled because no API license has been established.
- The two serialized XML example values are exempted from `no-invalid-media-type-examples`: Redocly 2.64.1 attempts to validate XML text as a JSON object. Literal XML strings are allowed by [OpenAPI 3.1 Example Objects](https://spec.openapis.org/oas/v3.1.0.html#example-object). `check.py` parses them and validates their contents separately. Shared reuse means the CLI reports many ignored occurrences of those same two values; no JSON examples or other rules are ignored.

## Publish with GitHub Pages

The [Pages workflow](../.github/workflows/pages.yml) validates generated-file
freshness, coverage, schemas, and examples with `check.py` (which also runs
`build.py --check`), then runs Redocly lint and HTML generation. Python
dependencies come from `uv.lock`; Redocly comes from `package-lock.json` via
`npm ci`. The build reads the checked-in reference and makes no OpenDART API calls.

On pull requests targeting `main`, the workflow uploads a `github-pages` artifact
containing the generated HTML for review, retained for seven
days. Pull requests do not deploy. Pushes to `main`, and manual runs on `main`,
deploy the same generated files after the build succeeds. Pages write and OIDC
permissions are limited to the deploy job. Deployments share a concurrency group
and an in-progress deployment is allowed to finish.

To enable publication:

1. In the GitHub repository, open **Settings → Pages** and select **GitHub Actions**
   as the source.
2. Commit the workflow, reference files, dependency manifests, and lockfiles, then
   merge or push to `main`.
3. Open the **API reference Pages** run in **Actions**. Its deployment links to the
   published site, normally `https://orestxherija.github.io/opendart/`. To rebuild
   without a new commit, use **Run workflow** with the `main` branch.

Only `site/` is published. Jekyll and a separate hosting service are unnecessary.
A custom domain can be configured in **Settings → Pages**, with the corresponding
DNS records at the domain provider. With Actions publication, a repository
`CNAME` file is not required. Pages hosts the reference; FSS hosts the API.

Dependabot checks npm, Python, and action dependencies. Review renderer updates
with the generated output and check navigation, search, color modes, and examples.

Upstream-guide refresh automation and compatibility comparisons are not yet
implemented. Refresh into a fresh cache and review the resulting diff separately
from publication. Formatting and schema lint cannot detect upstream changes;
[oasdiff](https://github.com/oasdiff/oasdiff) is one option for future contract
comparisons.

The relevant tool documentation is [Redocly lint](https://redocly.com/docs/cli/commands/lint),
[bundle](https://redocly.com/docs/cli/commands/bundle),
[Redoc CE's standalone module](https://redocly.com/docs/redoc/deployment/html), and
[GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
