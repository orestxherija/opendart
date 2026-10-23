# OpenDART MCP server: component design

Status: implemented (2026-10-22) on FastMCP 4. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) records the
implementation decisions and where the implementation deviates from this design.

This document proposes the tools, resources, and prompts for an MCP server built on `opendart-sdk`, aimed at
discretionary traders, trading and financial analysts, and portfolio managers who follow Korean listed companies. It is
based on a review of all 85 OpenDART services exposed by the SDK, the MCP specification and the installed
`mcp` 2.3.0 Python SDK, Anthropic's tool-design guidance, and published MCP design post-mortems. Sources are listed at
the end.

## Summary

- **13 tools** (plus 2 escape-hatch tools behind a setting that is off by default), all read-only, each named after a
  question an analyst asks: resolve a company, profile it, search and read filings, pull financials, compare peers,
  list material events, map ownership, capital structure, debt, dividends, governance, and a forward corporate-action
  calendar.
- **8 resources** (4 URI templates, 4 static) for stable context: company profile and filing index, filing outlines
  and sections, vocabulary and code tables, and server status.
- **11 prompts** that package multi-tool analyst workflows: company briefing, earnings review, event impact, dilution
  overhang, ownership and control, credit and liquidity, peer comparison, filings screen, pre-trade checklist,
  watchlist digest, filing summary.
- All 85 upstream services map onto these components (see the coverage matrix): the 36 "Report on Major Issues"
  services become one `get_corporate_events` tool; the 30 periodic-report extracts become six topical tools.
- Every tool accepts a company by name, stock code, or DART code and resolves it server-side; every result carries
  the resolved identity, an `as_of` date, source filing numbers, and caveats.

## Users and jobs

| Persona | Recurring questions this server must answer quickly |
| --- | --- |
| Discretionary trader | What did this name file today? Is there a dilutive deal, buyback, M&A, or distress event? What dates matter next (record, subscription, listing, suspension, conversion)? |
| Financial analyst | Latest income statement, balance sheet, cash flow (consolidated), margins and growth, ratios, auditor opinion, segment-level hints from the filing text, peer tables. |
| Portfolio manager | Who controls the company and has it changed? Free-float estimate, 5% holder moves, insider trades, dividend policy, leverage and refinancing wall, governance red flags across a watchlist. |

OpenDART has no prices, volumes, consensus, or news, and market data is out of scope for this server. The server
instructions say so explicitly so the model does not estimate prices or price-based metrics.

## Design principles

The research converged on a small number of rules; the component list below follows them.

1. Design from workflows, not endpoints. Anthropic: "A common error we've observed is tools that merely wrap existing
   software functionality or API endpoints" ([Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)).
   Block and Amplitude both replaced endpoint mirrors with one tool per object plus an action or category parameter
   ([Block](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers),
   [Amplitude](https://amplitude.com/blog/lessons-from-consolidating-our-mcp-server)).
2. Keep the model-visible surface small: 5–15 tools is the common recommendation, reliability degrades past 30–40,
   and definitions should stay under roughly 10K tokens
   ([Schmid](https://www.philschmid.de/mcp-best-practices), [Speakeasy](https://www.speakeasy.com/mcp/tool-design),
   [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)). The existing
   [hypn4/opendart-fss-mcp](https://github.com/hypn4/opendart-fss-mcp) exposes 85 one-to-one tools and no resources
   or prompts; this design is deliberately the opposite.
3. Do not make the model carry opaque IDs between calls. Amplitude found agents "calling the cohort lookup tool with
   invented IDs"; the sec-edgar precedent accepts "ticker or CIK" in one `identifier` parameter
   ([sec-edgar-mcp](https://github.com/stefanoamorelli/sec-edgar-mcp)). Here every tool takes `company` and resolves it.
4. Replace upstream codes with domain vocabulary and defaults (`period="latest"`, `basis="consolidated"`), and return
   semantic fields rather than raw codes ([AWS](https://aws.amazon.com/blogs/machine-learning/mcp-tool-design-practical-approaches-and-tradeoffs/)).
5. Bound and shape output: `response_format` concise/detailed, `limit` with `has_more`, truncation markers, and
   Markdown tables for the model's text view where it saves tokens (Anthropic, Block).
6. Errors are instructions: raise `ToolError` with the fix ("Ambiguous company; candidates are ..."), never an opaque
   code ([spec: tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)). "No data" from
   OpenDART is a normal answer, not an error, and is returned as an empty result with a note.
7. Annotate explicitly: omitted hints are treated pessimistically, so every tool sets `read_only_hint=True` and
   `open_world_hint=False` ([MCP blog](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)).
8. Put cross-tool guidance in the server `instructions`; keep long playbooks in prompts, not tool descriptions
   ([spec: discover](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)).
9. Use resources for stable, browsable context and prompts as reusable analyst macros; tools for parameterized
   retrieval ([server concepts](https://modelcontextprotocol.io/docs/learn/server-concepts),
   [SpecterOps](https://specterops.io/blog/2026/07/28/designing-an-mcp-server-for-ai-agents-bloodhound-hunter/)).
10. Do deterministic work in code (date extraction, unit normalization, YoY growth), not in the model's context
    ([Vercel](https://vercel.com/blog/the-second-wave-of-mcp-building-for-llms-not-developers)).

## What OpenDART gives us, and the constraints that shape the design

| Fact (from the SDK and `api_reference/`) | Consequence |
| --- | --- |
| Every service is keyed by an 8-digit `corp_code`; the directory is a ZIP download (`disclosures.corporation_codes`). | The server loads and indexes the directory in its lifespan and resolves names, 6-digit stock codes, and corp codes itself. |
| Periodic-report extracts (30 services) and financial statements take `fiscal_year` + `report_period` (`11011` annual, `11012` half-year, `11013` Q1, `11014` Q3). Data exists since 2015; indicators since 2022. | A `period`/`fiscal_year` vocabulary with a `latest` resolver that probes recent periods and caches the answer. |
| Major-issue services (36) and securities-registration services (6) take `corp_code` + filing date range and return many cryptic columns; the catalog has a human title for every column. | One events tool with a category vocabulary, generated field labels, per-kind headline templates, and date extraction. |
| `disclosures.search` is the only market-wide query (no `corp_code` → window limited to three months, 100 rows per page). | `search_filings` works with or without a company; it is also the cheap index used to decide which event services to call. |
| Amounts are strings with commas, blanks, and `-`; identifiers and dates are strings. | Normalize to integers/floats/ISO dates at the MCP layer; keep raw strings only in detailed mode. |
| Status `013` raises `NoDataError`; quota (`020`) raises `QuotaExceededError`; the SDK never retries. | Empty-with-note results for `013`; actionable `ToolError` for quota; one bounded retry for transport failures. |
| `document.xml` returns the Korean original as a ZIP (DART XML, or HTML for KRX disclosures): up to 9.7 MB expanded and 50 s to download in live samples. | `read_filing` parses leniently, shows the filing's own English headings and labels, and caches by filing number; see [FILING_DOCUMENTS.md](FILING_DOCUMENTS.md). |
| Consolidated (`CFS`) and separate (`OFS`) statements; many KOSDAQ names file only separate statements. | `basis="auto"` prefers consolidated and falls back with a note. |

## Shared conventions

These apply to every tool unless a tool says otherwise, and are documented once in the `opendart://reference/vocabulary`
resource and the server instructions rather than repeated in each description.

| Argument | Type and meaning |
| --- | --- |
| `company` | `str`: company name (English or Korean, suffixes like "Co., Ltd." ignored), 6-digit stock code (`005930`, `A005930`, `005930.KS` accepted), or 8-digit DART corp code. Exact code matches win; otherwise name matching prefers listed companies. Ambiguity raises `ToolError` listing up to five candidates with codes and markets; the model re-calls with a code. |
| `companies` | `list[str]`, 1–20 entries of the same forms (upstream batch limit is 100; 20 keeps results readable). |
| `period` | `"latest"`, `"FY"`, `"Q1"`, `"H1"`, `"Q3"`. `latest` means the most recent periodic report filed, of any kind. Results always state the period end date, since non-December fiscal years exist (the profile's `fiscal_year_end_month`). |
| `fiscal_year` | `int`, optional; defaults to the latest year that has the requested period. |
| `basis` | `"auto"`, `"consolidated"`, `"separate"`; `auto` = consolidated if filed, else separate, with a note. |
| `since`, `until` | ISO dates (`2025-01-01`) or relative durations (`"30d"`, `"6m"`, `"2y"`); `until` defaults to today (KST). |
| `limit`, `page` | Bounded result size (defaults 20–50) with `total`, `has_more`, and the exact next call in the result. |
| `unit` | `"million_krw"` (default, one decimal place), `"billion_krw"`, or `"krw"` (exact integers). Applies to monetary amounts only; per-share amounts (EPS, DPS), share counts, and ratios are never scaled. Detailed responses also carry exact won values. |
| `response_format` | `"concise"` (decision-relevant fields, Markdown table text) or `"detailed"` (all labeled fields plus raw strings). |

Every result is a Pydantic model (published as the tool's `outputSchema`) with: `company` (`name`, `english_name`,
`corp_code`, `stock_code`, `market`), `as_of` (server date, KST), `source_filings` (`filing_number`, `title`,
`filed`, `dart_url`), `notes` (fallbacks, estimates, coverage gaps), and the payload. Dates are ISO strings; markets are
`KOSPI`, `KOSDAQ`, `KONEX`, `OTHER`; filing numbers are returned because they are the handle for `read_filing` and for
citations, but never required as input where a company suffices.

Error vocabulary (`ToolError` text the model can act on): ambiguous company (candidates listed); unknown company
("call `find_company`"); window too wide for a market-wide search ("OpenDART limits searches without a company to
three months; narrow `since`/`until` or pass `company`"); quota exhausted ("retry after 00:00 KST"); upstream
unavailable (retried once, then surfaced). Argument validation errors are produced by the SDK's schema check.

Annotations: all tools are `read_only_hint=True`, `idempotent_hint=True`, `open_world_hint=False` (the universe is
the DART filer set). Tool order in `tools/list` is fixed to keep prompt caches warm.

## Tools

Shared arguments are omitted from the signatures below except where their defaults differ.

### `find_company`

Resolve free text to DART identities. Used by the model when it wants to confirm a match or pick among candidates;
all other tools call the same resolver internally.

```text
find_company(query: str, market: "all" | "KOSPI" | "KOSDAQ" | "KONEX" | "unlisted" = "all", limit: int = 10)
  -> matches[{corp_code, name, english_name, stock_code, market, last_modified}], best_match | None, note
```

Upstream: the cached corporation directory. Matching tiers: exact stock or corp code; exact normalized name in either
language; prefix; token and fuzzy match; listed companies first. `best_match` is set only when one candidate clearly
dominates, so callers can safely auto-select.

### `get_company_profile`

Identity and reference facts for one company, plus its latest periodic report so the model knows which fiscal
period "latest" means.

```text
get_company_profile(company) -> profile{names, codes, market, ceo, industry_code, fiscal_year_end_month,
  established, address, website, ir_url, phone}, latest_periodic_report{kind, fiscal_year, filed, filing_number}
```

Upstream: `disclosures.company`, one `disclosures.search` call filtered to periodic reports. Also served as the
`opendart://company/{corp_code}` resource.

### `search_filings`

The filing index: by company or market-wide, by category, by date window, by title text. This is the trader's "what
was filed" feed and the cheapest way to discover which detailed tool to call next.

```text
search_filings(company=None, categories: list[FilingCategory] | None = None, since="90d", until=None,
  market="all", title_contains=None, final_only=True, limit=50, page=1)
  -> filings[{filing_number, filed, company, title, submitter, category, is_amendment, dart_url}],
     total, page, has_more, next_call
```

`FilingCategory` is a friendly enum (about 25 values) over the ten upstream groups and the subcodes analysts use, such
as `annual_report`, `quarterly_report`, `major_issues`, `offerings`, `major_holding_report` (5% rule),
`insider_ownership_report`, `tender_offer`, `treasury_stock`, `ad_hoc_disclosure`, and `fair_disclosure`; the full
code mapping lives in the `filing-categories` resource. Without `company` the window is capped at three months and
the tool pages internally up to `limit`. KRX ad-hoc and fair disclosures (supply contracts, guidance) have no
structured service, so this index plus `read_filing` is the only route to them.

### `read_filing`

Navigate, read, and search the original filing. Documents are Korean even through the English API; the tool supplies
the English headings and table labels the filing itself carries, and the model translates the prose.

```text
read_filing(filing_number: str, mode: "outline" | "read" | "search" = "outline", section: str | None = None,
  query: str | None = None, document: str = "main", offset: int = 0, max_chars: int = 8000,
  labels: "english" | "korean" | "both" = "english") -> outline | Markdown chunk with tables | search hits
```

`section` takes an outline ID, a heading substring, or an alias stable across periodic reports (`business`,
`consolidated_notes`, `mdna`, `executive_pay`, ...); `document` selects an attachment such as the bundled audit
report. Upstream: `disclosures.document`. Full specification and evidence: [FILING_DOCUMENTS.md](FILING_DOCUMENTS.md).

### `get_financials`

One tool for every statement view, always returning a line-items-by-periods table. OpenDART returns the current,
prior, and two-years-prior columns in one call, so `years=1` already yields three annual columns.

```text
get_financials(company, view: "summary" | "income" | "balance" | "cash_flow" | "comprehensive_income"
  | "equity_changes" | "ratios" | "equity_investments" | "preliminary" = "summary", basis="auto",
  period="latest", fiscal_year=None, years: int = 1, accounts: list[str] | None = None, unit="million_krw",
  response_format="concise")
  -> periods[{label, end_date, fiscal_year, period}], rows[{account, account_id?, values[], cumulative[]?}],
     derived{revenue_growth, operating_margin, net_margin, debt_to_equity, ...}, basis_used, currency
```

- `summary`: the curated major accounts (`fnltt_singl_acnt`) plus derived margins and growth computed in code and
  marked as derived.
- `income`, `balance`, `cash_flow`, `comprehensive_income`, `equity_changes`: the full statement
  (`fnltt_singl_acnt_all` filtered by statement type); `accounts` narrows rows by substring so the model can ask for
  "Revenue, Operating" instead of 150 rows.
- `ratios`: profitability, stability, growth, and activity indicators (`fnltt_singl_indx`, four calls; available
  from fiscal 2022).
- `equity_investments`: holdings in other companies with book values (`otr_cpr_invstmnt_sttus`), the input for
  sum-of-the-parts questions.
- `preliminary`: the latest unaudited quarterly results from a KRX fair disclosure, typically weeks before the
  quarterly report: revenue, operating, pretax, and net profit, with QoQ and YoY changes. No structured service
  carries these; the `read_filing` parser extracts them (see [FILING_DOCUMENTS.md](FILING_DOCUMENTS.md)).
- `years > 1` chains calls backwards; quarterly views expose both the period amount and the cumulative amount.

### `compare_companies`

Peer table from the multi-company services, one upstream call for accounts and four for ratios.

```text
compare_companies(companies, metrics: "key_accounts" | "ratios" | "both" = "key_accounts", fiscal_year=None,
  period="FY", basis="consolidated", unit="million_krw", response_format="concise")
  -> columns[metric], rows[{company, values[]}], missing[{company, reason}]
```

Upstream: `fnltt_multi_acnt`, `fnltt_cmpny_indx`. Companies missing a filing are listed in `missing` rather than
silently dropped.

### `get_corporate_events`

Material events a company decided or filed: capital raises, convertible and hybrid issues, buybacks, M&A and
restructurings, asset deals, distress and legal events, overseas listings, and registered offerings. This single tool
replaces 42 upstream services (36 major-issue reports plus 6 securities-registration summaries).

```text
get_corporate_events(company, categories: list[EventGroup | EventKind] | None = None, since="1y", until=None,
  limit=50, response_format="concise")
  -> events[{kind, group, filed, board_date, filing_number, headline, key_terms{...}, dates[{what, date}],
     flags[], dart_url}], coverage{kinds_queried, kinds_with_data}
```

Event vocabulary (group → kinds, upstream SDK method in parentheses):

| Group | Kinds |
| --- | --- |
| `capital_raise` | `rights_or_third_party_issue` (`piic_decsn`), `bonus_issue` (`fric_decsn`), `combined_paid_and_bonus_issue` (`pifric_decsn`), `equity_offering_registration` (`estk_rs`), `depositary_receipt_registration` (`stkdp_rs`) |
| `convertible_and_hybrid_debt` | `convertible_bond` (`cvbd_is_decsn`), `bond_with_warrants` (`bdwt_is_decsn`), `exchangeable_bond` (`exbd_is_decsn`), `contingent_capital_bond` (`wd_cocobd_is_decsn`), `debt_offering_registration` (`bd_rs`) |
| `buyback` | `treasury_stock_acquisition` (`tsstk_aq_decsn`), `treasury_stock_disposal` (`tsstk_dp_decsn`), `treasury_trust_contract` (`tsstk_aq_trctr_cns_decsn`), `treasury_trust_termination` (`tsstk_aq_trctr_cc_decsn`) |
| `capital_reduction` | `capital_reduction` (`cr_decsn`) |
| `mna_and_restructuring` | `merger` (`cmp_mg_decsn`), `split_off` (`cmp_dv_decsn`), `split_merger` (`cmp_dvmg_decsn`), `share_swap_or_transfer` (`stk_extr_decsn`), `business_acquisition` (`bsn_inh_decsn`), `business_transfer` (`bsn_trf_decsn`), `merger_registration` (`mg_rs`), `share_swap_registration` (`extr_rs`), `split_registration` (`dv_rs`) |
| `asset_and_investment_deals` | `acquire_other_company_shares` (`otcpr_stk_invscr_inh_decsn`), `transfer_other_company_shares` (`otcpr_stk_invscr_trf_decsn`), `acquire_equity_linked_bonds` (`stkrtbd_inh_decsn`), `transfer_equity_linked_bonds` (`stkrtbd_trf_decsn`), `acquire_tangible_assets` (`tgast_inh_decsn`), `transfer_tangible_assets` (`tgast_trf_decsn`), `asset_deal_put_back_option` (`ast_inhtrf_etc_ptbk_opt`) |
| `distress_and_legal` | `default_or_bankruptcy` (`df_ocr`), `rehabilitation_filing` (`ctrcvs_bgrq`), `creditor_workout_start` (`bnk_mngt_pcbg`), `creditor_workout_suspension` (`bnk_mngt_pcsp`), `dissolution_cause` (`ds_rs_ocr`), `business_suspension` (`bsn_sp`), `lawsuit` (`lwst_lg`) |
| `overseas_listing` | `overseas_listing_decision` (`ov_lst_decsn`), `overseas_listing_completed` (`ov_lst`), `overseas_delisting_decision` (`ov_dlst_decsn`), `overseas_delisting` (`ov_dlst`) |

Per-kind behavior is data-driven from a generated registry: a headline template (for a convertible bond: face
value, coupon and yield, conversion price and share count as a percentage of shares outstanding, conversion window,
refixing floor), the `key_terms` subset shown in concise mode, the date fields that feed the calendar, and
`flags` such as backdoor-listing indicators, third-party allotment within six months, put-option agreements, FTC
reporting, and amendments. Detailed mode returns every column with its catalog label.

Call strategy: when `categories` is omitted the tool first runs `search_filings` for major-issue and offering
categories in the window and queries only the kinds whose titles appear, falling back to a concurrent fan-out with
caching. Rows are grouped by filing number so amended filings do not look like new events; a debt registration
that offers several tranches becomes one event per tranche.

### `get_ownership`

Who controls the company, how that has changed, and who has been buying or selling: largest shareholder and
related parties, changes of control, minority shareholders, treasury shares, 5% holder reports, and insider
(executive and major shareholder) ownership reports.

```text
get_ownership(company, activity_window="180d", period="latest", fiscal_year=None, response_format="concise")
  -> snapshot{largest_shareholder_group[{name, relation, share_class, shares, pct_begin, pct_end}],
     controlling_pct, minority{holders, holder_pct, shares, share_pct}, treasury_shares, shares_outstanding,
     free_float_estimate_pct},
     control_changes[{date, new_largest_shareholder, shares, pct, cause}],
     major_holder_reports[{filed, reporter, report_type, shares, change_in_shares, pct, change_in_pct, reason}],
     insider_reports[{filed, reporter, position, is_registered_officer, shares, change, pct}]
```

Upstream: `hyslr_sttus`, `hyslr_chg_sttus`, `mrhl_sttus`, `stock_totqy_sttus`, `majorstock`, `elestock`. The
free-float estimate (outstanding minus controlling group minus treasury) is marked as an estimate in `notes`.

### `get_capital_structure`

Share counts and how they got there: authorized and issued shares by class, treasury stock movements, capital
increases and reductions, and whether raised money was used as promised.

```text
get_capital_structure(company, sections: list["shares" | "treasury_stock" | "capital_changes"
  | "use_of_proceeds"] | None = None, period="latest", fiscal_year=None, response_format="concise")
```

Upstream: `stock_totqy_sttus`, `tesstk_acqs_dsps_sttus`, `irds_sttus`, `pssrp_cptal_use_dtls`,
`prvsrp_cptal_use_dtls`. Outstanding dilutive instruments are events, so the description points to
`get_corporate_events(categories=["convertible_and_hybrid_debt", "capital_raise"])`; the `dilution_overhang` prompt
combines both.

### `get_debt_profile`

Refinancing and credit view from the periodic reports: a normalized maturity ladder for corporate bonds, short-term
bonds, commercial paper, hybrid and contingent capital securities, plus the issuance record with coupons, ratings,
maturities, and underwriters.

```text
get_debt_profile(company, period="latest", fiscal_year=None, response_format="concise")
  -> ladder[{instrument, buckets[{maturity_bucket, amount}], total}], issuance[{date, type, amount, coupon, rating,
     rating_agency, maturity, underwriter, redeemed}], derived{total_debt_securities, due_within_1y_pct}
```

Upstream: `cprnd_nrdmp_blce`, `srtpd_psndbt_nrdmp_blce`, `entrprs_bil_scrits_nrdmp_blce`,
`new_capl_scrits_nrdmp_blce`, `cndl_capl_scrits_nrdmp_blce`, `det_scrits_isu_acmslt`.

### `get_dividends`

Dividend history by share class: dividend per share, total payout, payout ratio, yield as filed, and the earnings
basis, across fiscal years.

```text
get_dividends(company, years: int = 3, response_format="concise")
  -> rows[{measure, share_class, values_by_year{}}], notes
```

Upstream: `alot_matter` (one call covers three fiscal years; `years=5` makes two calls). Yields are as reported in
the filing, not recomputed, because the server has no prices.

### `get_governance`

Audit and governance facts that change a risk assessment: auditor, opinion type, emphasis-of-matter and key audit
matters, audit and non-audit fees, outside-director composition and changes, executives, compensation, and
employees.

```text
get_governance(company, sections: list["audit" | "board" | "executives" | "compensation" | "employees"]
  = ["audit", "board"], fiscal_year=None, period="FY", response_format="concise")
  -> audit{auditor, opinion, emphasis, key_audit_matters, fees, non_audit_services, auditor_changed_vs_prior_year},
     board{directors, outside_directors, changes}, executives[...], compensation{...}, employees{...}, flags[]
```

Upstream: the twelve audit, board, executive, compensation, and employee services listed in the coverage matrix
(remuneration V2 services preferred, V1 as fallback). `flags` surfaces non-unqualified opinions, going-concern
language, and an auditor change (one extra call for the prior year).

### `get_corporate_action_calendar`

Forward-looking dates extracted from events for one company or a watchlist, sorted by date: subscription and
payment dates, record dates, shareholder meetings, appraisal-rights windows, trading suspensions, new-share listing
dates, conversion windows opening, short-sale restriction windows around rights issues, buyback and disposal
periods, and bond maturities.

```text
get_corporate_action_calendar(companies, horizon="90d", include_past: str | None = None,
  kinds: list[EventGroup | EventKind] | None = None)
  -> items[{date, company, action, source_kind, filing_number, details}], as_of
```

Upstream: the same registry as `get_corporate_events` (date fields per kind) plus maturities from the latest
periodic reports' debt tables, selected by the calendar-only kind `debt_maturity`. This is the highest-value
component per call for discretionary traders; the registry makes the date extraction deterministic.

### Escape hatch: `list_services` and `call_service` (off by default)

`list_services(query)` searches the 85 service descriptions; `call_service(service, params)` calls one with the same
labels and normalization, as a stated last resort ([Massive's pattern](https://github.com/polygon-io/mcp_polygon)).
Both are built but registered only when `OPENDART_MCP_TOOLS__ENABLE_SERVICE_TOOLS=true` (a `tools` settings group
beside `http`). Evaluation runs enable them to find gaps; turning them on in production follows that evidence.

## Resources

Resources are application-controlled context: hosts can attach, browse, or cache them without a model call.
Templates use RFC 6570 syntax supported by `mcp` 2.3.0; `{corp_code}` arguments are completable.

| URI | MIME | Content |
| --- | --- | --- |
| `opendart://company/{corp_code}` | `application/json` | Same payload as `get_company_profile`. |
| `opendart://company/{corp_code}/filings{?since,category}` | `application/json` | Filing index for the company (defaults: 90 days, all categories). |
| `opendart://filing/{filing_number}` | `application/json` | Filing metadata and outline: company, title, form, filed, amendment summary, sections, DART viewer URL. |
| `opendart://filing/{filing_number}/sections/{section_id}` | `text/markdown` | One rendered section, unpaged (the paged view is `read_filing`). |
| `opendart://reference/vocabulary` | `text/markdown` | Period, market, basis, unit, date, and category vocabulary; limitations (no prices, data lag, amendments). |
| `opendart://reference/filing-categories` | `application/json` | Friendly category names mapped to `pblntf_ty`/`pblntf_detail_ty` codes. |
| `opendart://reference/event-kinds` | `application/json` | Event groups, kinds, upstream services, key terms, and date fields. |
| `opendart://server/status` | `application/json` | `as_of` (KST), directory load time and size, upstream calls today, cache statistics, key configured. |

Reference resources are annotated `audience: ["assistant"]` with moderate priority and `cacheScope: public`; the
status resource is private and uncached. An XBRL taxonomy template over `xbrl_taxonomy` is cheap to add later.

## Prompts

Prompts are user-invoked macros (slash commands in most hosts). Each returns a message sequence that names the tools
to call, the analysis rules (consolidated basis unless noted, cite filing numbers, mark estimates, state that prices
are unavailable), and an output template. Arguments are strings; `company` and `companies` are completable.

| Prompt | Arguments | Workflow and output |
| --- | --- | --- |
| `company_briefing` | `company` | Profile, latest financial summary, ownership snapshot, events in the last year, governance flags; one-page brief with a "what to watch" list. |
| `earnings_review` | `company`, `fiscal_year=""`, `period="latest"` | Summary and full statements for the period, YoY and QoQ comparison, margins, cash conversion, balance-sheet changes, audit opinion if annual; tabular review with notable line items. |
| `event_impact` | `company`, `event=""`, `filing_number=""` | Pull the event (or read the filing), extract terms, compute dilution or leverage effect against capital structure, list dates, compare with prior similar events; impact memo. |
| `dilution_overhang` | `company`, `lookback="3y"`, `share_price=""` | Inventory CB/BW/EB, rights issues, stock options, and treasury disposals; potential new shares versus outstanding; conversion prices and refixing floors versus the user-supplied price; table plus conclusion. |
| `ownership_and_control` | `company` | Ownership snapshot, control changes, 5% and insider activity in the window; free-float estimate; control-risk assessment. |
| `credit_and_liquidity` | `company` | Debt ladder, recent issuance and ratings, cash and operating cash flow from financials, interest burden, distress events, going-concern language; refinancing-risk memo. |
| `peer_comparison` | `companies`, `fiscal_year=""`, `focus="all"` | `compare_companies` for accounts and ratios; ranked table with commentary on outliers. |
| `filings_screen` | `since="1d"`, `market="KOSPI,KOSDAQ"`, `focus="all"` | Market-wide `search_filings` by category, then `get_corporate_events` for the names that matter; prioritized list of tradable events with dates. |
| `pre_trade_checklist` | `company`, `direction="long"`, `horizon="3m"` | Calendar within the horizon, dilution overhang, ownership changes, governance and audit flags, distress and legal events, recent amendments; pass/flag checklist. |
| `watchlist_digest` | `companies`, `since="7d"` | New filings and events per name since the date; grouped digest with items requiring action first. |
| `summarize_filing` | `filing_number`, `focus=""` | Outline, then targeted reads of the relevant sections; English summary of the Korean filing with key numbers, dates, and section IDs, quoting Korean terms where translation is uncertain. |

Prompts may embed the company profile resource directly, saving a tool call, and should keep their instructions under
roughly 300 words so they do not crowd the context.

## Coverage matrix

| Upstream services (SDK methods) | Component |
| --- | --- |
| `disclosures.search` | `search_filings`; index step inside `get_corporate_events`; `latest_periodic_report` in the profile |
| `disclosures.company` | `get_company_profile`; `opendart://company/{corp_code}` |
| `disclosures.document` | `read_filing`; `get_financials(view="preliminary")`; filing resources |
| `disclosures.corporation_codes` | Lifespan directory; `find_company`; argument completions |
| `fnltt_singl_acnt`, `fnltt_singl_acnt_all`, `fnltt_singl_indx` | `get_financials` views |
| `fnltt_multi_acnt`, `fnltt_cmpny_indx` | `compare_companies` |
| `xbrl_taxonomy` | Optional reference resource |
| `fnltt_xbrl` | Not exposed in v1 (full statements already cover the accounts). The archive is XBRL XML: instance, schema, and linkbases, including English labels |
| `stock_totqy_sttus`, `tesstk_acqs_dsps_sttus`, `irds_sttus`, `pssrp_cptal_use_dtls`, `prvsrp_cptal_use_dtls` | `get_capital_structure` (shares also feed `get_ownership`) |
| `hyslr_sttus`, `hyslr_chg_sttus`, `mrhl_sttus`, `majorstock`, `elestock` | `get_ownership` |
| `cprnd_nrdmp_blce`, `srtpd_psndbt_nrdmp_blce`, `entrprs_bil_scrits_nrdmp_blce`, `new_capl_scrits_nrdmp_blce`, `cndl_capl_scrits_nrdmp_blce`, `det_scrits_isu_acmslt` | `get_debt_profile` |
| `alot_matter` | `get_dividends` |
| `accnut_adtor_nm_nd_adt_opinion`, `adt_servc_cncls_sttus`, `accnut_adtor_non_adt_servc_cncls_sttus`, `outcmpny_drctr_nd_change_sttus`, `exctv_sttus`, `emp_sttus`, `unrst_exctv_mendng_sttus`, `hmv_audit_all_sttus`, `hmv_audit_indvdl_by_sttus` (+v2), `indvdl_by_pay` (+v2), `drctr_adt_all_mendng_sttus_gmtsck_confm_amount`, `drctr_adt_all_mendng_sttus_mendng_pymntamt_ty_cl` | `get_governance` sections |
| `otr_cpr_invstmnt_sttus` | `get_financials(view="equity_investments")` |
| 36 major-issue services | `get_corporate_events` kinds; `get_corporate_action_calendar` |
| `estk_rs`, `bd_rs`, `stkdp_rs`, `mg_rs`, `extr_rs`, `dv_rs` | `get_corporate_events` registration kinds; `get_corporate_action_calendar` |

All 85 services are reachable; 84 through the abstractions and `fnltt_xbrl` deferred.

## Implementation notes

- **SDK facts that apply** (`mcp` 2.3.0, read from the installed source): `MCPServer(name, instructions=...,
  version=..., lifespan=...)`; `@server.tool(annotations=ToolAnnotations(...))`; Pydantic return types become
  `outputSchema` and both `structuredContent` and text; `Context` is injected by annotation; `ToolError` yields
  `isError` results with the message; `@server.resource("opendart://...{corp_code}", mime_type=...)` registers
  templates; `@server.prompt()` arguments use `Annotated[str, Field(description=...)]`; one `@server.completion()`
  handler serves prompt and template argument completion; `cache_hints` set `ttlMs`/`cacheScope`; list pagination and
  tasks are not supported; `ctx.info()` logging is deprecated (use stdlib logging); elicitation only works on
  stateful handshake-era sessions, so ambiguity is handled by `ToolError` candidates, with `Resolve`/`Elicit`
  parameter injection as a later enhancement. Pass `instructions=` by keyword.
- **Text view**: to return Markdown tables to the model and typed JSON to the host, tools return
  `Annotated[CallToolResult, Model]` with a text block and `structured_content`; this is the one place the SDK's
  default JSON rendering is overridden.
- **Lifespan state**: one `OpenDart` client; the directory index (both names, stock codes, suffix stripping,
  optional fuzzy scorer); a response cache keyed by SDK method and arguments (24 h for periodic data and profiles,
  15–60 min for filings and events); a "latest period" cache per company; a daily upstream call counter; a
  concurrency semaphore (about five in flight) and a single retry for `UnavailableError`, never for quota.
- **Generated registry and labels**: extend `scripts/` with a generator that reads `api_reference/sources/catalog.json`
  and emits (a) field-name → label maps for every service and (b) the event-kind registry skeleton (service, SDK
  method, group, date fields), mirroring the SDK generator. Headline templates and key-term selections stay handwritten.
- **Normalization**: amounts (`"1,234"` → `1234`, `"-"` → `null`, leading `-` negative), percentages, dates
  (`YYYYMMDD` and `YYYY.MM.DD` → ISO), markets and report codes to labels, filing date derived from the first eight
  digits of the filing number.
- **Tool budget**: 13 tools with 100–150-word descriptions is roughly 6–8K tokens of definitions; measure it in CI
  and fail if it exceeds 10K. Keep descriptions free of dates and other volatile text.
- **Testing**: in-process `server.call_tool`/`read_resource`/`get_prompt` with `httpx2.MockTransport` injected
  through the lifespan; fixtures from the reference examples; golden tests for headlines, date extraction, and
  normalization; an offline task suite (resolve "Samsung", "latest Q3 income statement for 005930", "CB issuance last
  year") that counts calls and tokens, plus an opt-in live suite like the contract tests.
- **Module layout** (500-line file cap): `resolver`, `periods`, `normalize`, `registry`, tool modules, `resources`,
  `prompts`. `ping` moves to a `/health` custom route (`MCPServer.custom_route`) so it does not spend a tool slot;
  `scripts/check_mcp.py` then calls `find_company` instead.

## Delivery plan

1. Foundation: lifespan, directory and resolver, normalization, `find_company`, `get_company_profile`,
   `search_filings`, `get_financials`, reference resources and status, server instructions, `/health` route.
2. Events: generated labels and registry, `get_corporate_events`, `get_ownership`,
   `get_corporate_action_calendar`, prompts `company_briefing`, `event_impact`, `filings_screen`.
3. Depth: `read_filing` and the preliminary-earnings view, `get_capital_structure`, `get_debt_profile`,
   `get_dividends`, `get_governance`, `compare_companies`, remaining prompts, completions, cache hints.
4. Evaluation and optional extras: escape-hatch tools behind their switch, task suite and transcript review (with
   the switch on, to find gaps), description tuning, then the Skills extension and MCP Apps for interactive tables.

## Open decisions

Resolved: document format (live samples, [FILING_DOCUMENTS.md](FILING_DOCUMENTS.md)); default unit (million won);
escape-hatch tools (built behind a switch, off by default); market data (out of scope, no integration).

1. **Name languages**: search results return English company names, and the catalog lists both a formal name and an
   English name in the directory; confirm which languages the directory holds when building the resolver.
2. **Entity disambiguation UX**: `ToolError` candidates only, or also elicitation for hosts that support it.

## Sources

The design principles link to the pages they draw on. Further references used:

- MCP 2026-07-28: [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog),
  [resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources),
  [prompts](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts),
  [completion](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/completion),
  [caching hints](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)
- MCP Python SDK v2: [what's new](https://py.sdk.modelcontextprotocol.io/whats-new/),
  [migration](https://py.sdk.modelcontextprotocol.io/migration/),
  [structured output](https://py.sdk.modelcontextprotocol.io/servers/structured-output/),
  [dependencies and elicitation](https://py.sdk.modelcontextprotocol.io/handlers/dependencies/)
- Anthropic: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents),
  [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
  [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
