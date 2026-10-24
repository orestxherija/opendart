# Filing documents: observed format and `read_filing` specification

Status: findings from live samples taken on 2026-10-22, and the `read_filing` specification they support. Companion to
[COMPONENT_DESIGN.md](COMPONENT_DESIGN.md).

## Method

Seventeen filings were chosen from `disclosures.search` to cover the document families analysts read:

- annual, semi-annual, and quarterly reports, from KOSPI and KOSDAQ filers;
- major-issue reports (a convertible bond, a merger, and an amended convertible bond);
- 5% holding reports (general and short form), an insider ownership report, and a treasury stock result report;
- an unlisted company's audit report, an amended equity registration statement, and a post-issuance report;
- four KRX exchange disclosures: two preliminary-earnings fair disclosures, one ad hoc disclosure, and one exchange
  notice.

A second batch targeted filings likely to bundle attachments: two KRX corporate value-up plans, a KRX IR event
notice, a foreign issuer's amended decision report, and three shareholders' meeting notices. Each archive was
downloaded through `disclosures.document` and inspected in memory; one extra download tested the SDK's default
timeouts. Raw documents are not committed. Tests should use synthetic fixtures that reproduce the structures below.

## Findings

### Language

Documents are the Korean originals. The English API translates only search metadata: report titles and company names
come back in English, submitter names in Korean. The documents carry English scaffolding the server can use:

- `TITLE` and `COVER-TITLE` elements carry the English heading in an `ENG` attribute on 95–100% of sections.
- Label cells (`TH`, `TD`, `TU`) often have `ENG` too: 50–80% of cells in short structured forms (convertible bond
  decision 150 of 282, 5% short form 183 of 226, insider report 73 of 103), but only 5–10% in periodic reports,
  where they cover standard table headers.
- Statement tables tag value cells with IFRS element names (`TE ACODE="ifrs-full_CashAndCashEquivalents"`), which give
  an English concept name for each row.

Narrative text, footnotes, and most table rows in periodic reports remain Korean. The model translates; the server
supplies English headings and labels and never presents its own translation.

KRX filing titles in search results carry runs of padding spaces and sometimes a Korean suffix, for example
`Corporate Value-up Plan (Voluntary Disclosure)   (PBR 개선 계획 제출 기업)`; `search_filings` collapses whitespace.

### Two formats

| | FSS filings | KRX exchange disclosures |
| --- | --- | --- |
| Filing numbers | `YYYYMMDD` + `00xxxx` | `YYYYMMDD` + `80xxxx` (KOSPI, search `rm="S"`) or `90xxxx` (KOSDAQ, `rm="K"`) |
| Markup | DART XML (`xsi:noNamespaceSchemaLocation="dart4.xsd"`) | HTML "xforms" page with inline CSS |
| Encoding | UTF-8, declared | UTF-8, although the page declares `euc-kr` |
| Well-formed XML | No for 11 of 15 members: unescaped `&` in prose ("R&D", "C&T", "M&A") | No |
| Structure | `DOCUMENT-NAME ACODE` (form code), cover `LIBRARY`, nested `SECTION-1` to `SECTION-4` with `TITLE`, then `P`, `TABLE`, `TABLE-GROUP`, `IMAGE`, `PGBRK` | `<title>` of the form `company/form/(date)title`, one or two tables, no sections |
| Content | Narrative, statements, notes, structured forms | Key/value forms (ad hoc decisions, exchange notices) and the preliminary-earnings table |

A lenient tag-soup parser is required. Python's `html.parser.HTMLParser` handled every sample. On the largest member
(7.9 MiB) it took 2.0 s with a 20 MiB peak (tracemalloc), which fits the container's 256 MiB limit but must run in a
worker thread.

### Archive layout

The main document is `{filing_number}.xml`. Attachments are `{filing_number}_{form_code}.xml`: the annual report
carried its audit report (`_00760`) and consolidated audit report (`_00761`). A standalone audit report contains only
the `_00760` member.

The archive does not carry every attachment. The DART website lists eight for the sampled annual report; the API
archive held only the two audit reports. The six missing ones are listed below.

| Attachment | Content on the DART website |
| --- | --- |
| Articles of incorporation | Text, about 15K characters |
| Internal accounting control report | Text, about 20K characters, plus 24 images |
| Business report to shareholders | 106 images, little text |
| Audit committee's audit report | Scanned image |
| Audit committee opinion on internal monitoring | Two scanned pages |
| Treasury stock report | Scanned image |

The API gives no list of omitted attachments, so for annual reports `read_filing` adds a note naming these typical
attachments and links to the DART viewer. This comes from one filing; other report types may differ.

None of the 24 archives contained an image, PDF, or other binary file; every member was DART XML or KRX HTML.

- `IMG` elements hold only a filename (for example `대표이사 확인서.jpg`), and the file is not shipped. Content that
  exists only as images is therefore unavailable: CEO certifications, scanned internal-control report pages, market
  charts, organization charts, and small-business or venture certificates.
- KRX value-up plans mention an attached plan document that the archive omits. IR notices point to the company's
  website for presentation materials.
- The outline marks sections whose content is image-only. Any future non-XML member is listed in the outline with
  its name and size, but not rendered.

### Size and latency

| Document | Form code | Members | Expanded | Text chars | Sections | Download |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Annual report (KOSPI) | 11011 | 3 | 9.7 MB | 911K | 163 | 50 s |
| Semi-annual report (KOSPI) | 11012 | 1 | 6.8 MB | 638K | 135 | 9 s |
| Equity registration statement (amended) | 10001 | 1 | 4.5 MB | 645K | 69 | 32 s |
| Quarterly report (KOSDAQ) | 11013 | 1 | 1.1 MB | 105K | 73 | 8 s |
| Post-issuance report | 10800 | 1 | 194 KB | 23K | 19 | 1.9 s |
| 5% holding report, general | 00636 | 1 | 202 KB | 14K | 28 | 1.7 s |
| Convertible bond decision | 11324 | 1 | 87 KB | 16K | 2 | 1.2 s |
| Merger decision | 11344 | 1 | 74 KB | 11K | 5 | 1.0 s |
| Treasury stock acquisition result | 00681 | 1 | 45 KB | 3.8K | 10 | 0.4 s |
| Insider ownership report | 00634 | 1 | 25 KB | 1.5K | 6 | 0.6 s |
| KRX disclosures (4 samples) | none | 1 | 4–22 KB | under 2K | none | 0.2–0.4 s |

Text characters count tag-stripped text with whitespace collapsed; the annual report row sums its three members.

With the SDK's default 5 s phase timeouts, the annual report download failed with `ReadTimeout` after 52 s: the
upstream paused for more than five seconds mid-transfer. With a 60 s read timeout the same download completed in 50 s.

### Sections

`TITLE AASSOCNOTE` holds a section code. In periodic reports, all 51 codes were identical across the KOSPI annual
report, the KOSPI semi-annual report, and the KOSDAQ quarterly report, each with an English title, so they work as
stable section IDs and alias targets. Other forms use their own codes: `D-1-*` in 5% reports, and `D-0-1-0-0` for the
decision table in major-issue reports. Sections without a code get `s{ATOCID}` or their ordinal path.

Semi-annual and quarterly reports keep the MD&A headings (`D-0-4-*`), each with a one-line omission statement; the
outline marks such sections as placeholders.

### Structured markup

- `TE ACODE` on value cells: IFRS element names in statements and notes; form field codes in event and ownership
  reports (`STK_CNT`, `SPC_NM`).
- `TU AUNIT` and `AUNITVALUE`: coded values such as dates (`EXP_DT` = `20311030`) and enumerations.
- `TABLE ACLASS="EXTRACTION"` and `TABLE-GROUP ACLASS` (`CB_PUB`, `SUM_INF`) mark the tables that feed the
  structured services. Event terms therefore come from `get_corporate_events`, not from parsing documents.
- Units are text inside a table or its caption: `(단위 : 백만원)`, `단위 : 조원, %`, `구분(단위 : 백만원, %)`.

### Amendments

Amended filings start with a `정 정 신 고 (보고)` section naming the corrected document and its original filing date,
followed by a table of item, reason, before, and after. It is the fastest way to see what changed, so the outline
extracts it.

### Preliminary earnings

KRX fair disclosures titled "Report on Business Performance according to Consolidated Financial Statements (Fair
Disclosure)" used one template on both markets. It defines the periods (current quarter, prior quarter, year-ago
quarter, year to date), then reports revenue, operating profit, pretax profit, net profit, and net profit attributable
to owners, each with quarter-on-quarter and year-on-year change and turnaround flags. Units differ by filer: trillion
won for Samsung, million won for SGC E&C. Companies publish these weeks before the quarterly report, and no structured
service carries them, so the component design adds `get_financials(view="preliminary")` on top of this parser. The
"Forecast" and "Interim" variants seen in search need samples before they are parsed.

## `read_filing` specification

```text
read_filing(filing_number: str, mode: "outline" | "read" | "search" = "outline", section: str | None = None,
  query: str | None = None, document: str = "main", offset: int = 0, max_chars: int = 8000,
  labels: "english" | "korean" | "both" = "english")
```

### Arguments

| Argument | Meaning |
| --- | --- |
| `filing_number` | 14-digit number from `search_filings` or any `source_filings` entry. |
| `mode` | `outline` (default): document map without body text. `read`: rendered text of one section or the whole document, paged. `search`: passages matching `query`. |
| `section` | For `read`, and to scope `search`: an outline ID (`D-0-3-3-0`), an alias (below), or a heading substring matched against English, then Korean, titles. Omitted means the whole document in order. |
| `query` | Search terms in Korean or English. Body text is Korean, so Korean terms find prose (`전환사채` for convertible bonds); English terms match headings and labels only. |
| `document` | `main`, or an attachment listed in the outline: `audit_report`, `consolidated_audit_report`, or its form code. |
| `offset`, `max_chars` | Paging in characters of rendered text. `max_chars` defaults to 8,000 and is capped at 30,000. |
| `labels` | Language of headings and labels. `english` uses `ENG` where present and falls back to Korean; `both` renders `English (Korean)`. |

Korean text is expensive in tokens. Until token counts are measured, assume up to one token per Hangul character;
8,000 characters stays well under common host limits (Claude Code truncates tool results at 25,000 tokens).
Evaluation should calibrate the default.

### Results

Every mode returns `filing` (number, form code, form name in English and Korean, company, filing date, amendment
flag, `dart_url`, and `language: "ko"`), `as_of`, and `notes`.

- `outline`:
  - `documents[{key, form_code, name_en, name_ko, chars}]`;
  - `sections[{id, level, title_en, title_ko, chars, tables, placeholder}]` for the selected document;
  - `amendment{original_filed, changes[{item, reason, before, after}]}`, when present;
  - `suggested_sections`: for periodic reports, the aliases present in this document.
- `read`:
  - `content` (Markdown), `section`, `offset`, `next_offset`, `total_chars`, and `truncated`;
  - `tables[{caption, unit, header[], rows[][]}]` for tables in the returned chunk, so hosts get typed data while
    the model reads Markdown.
- `search`:
  - `hits[{section_id, section_title_en, offset, snippet}]`: up to 20, with about 300 characters of context each;
  - `total_hits`. Each hit's `offset` feeds a follow-up `read`.

### Section aliases for periodic reports

| Alias | Codes |
| --- | --- |
| `company_overview` | `D-0-1-1-0` |
| `share_capital` | `D-0-1-3-0`, `D-0-1-4-0` |
| `business` | `D-0-2-0-0` and its `L-0-2-*` children |
| `risk_and_derivatives` | `L-0-2-5-L1` |
| `contracts_and_rnd` | `L-0-2-6-L1` |
| `financial_summary` | `D-0-3-1-0` |
| `consolidated_statements`, `consolidated_notes` | `D-0-3-2-0`, `D-0-3-3-0` |
| `separate_statements`, `separate_notes` | `D-0-3-4-0`, `D-0-3-5-0` |
| `dividends` | `D-0-3-6-0` |
| `use_of_proceeds` | `D-0-3-7-0` |
| `mdna` | `D-0-4-0-0` (substantive in annual reports only) |
| `audit` | `D-0-5-0-0` |
| `board` | `D-0-6-1-0` |
| `shareholders` | `D-0-7-0-0` |
| `executives_and_employees`, `executive_pay` | `D-0-8-1-0`, `D-0-8-2-0` |
| `affiliates` | `D-0-9-0-0` |
| `related_party_transactions` | `D-0-10-0-0` |
| `contingent_liabilities` | `D-0-11-2-0` |
| `sanctions` | `D-0-11-3-0` |
| `subsequent_events` | `D-0-11-4-0` |

Both sampled non-financial filers used the `L-0-2-*-L1` business-section codes. Banks, insurers, and other
financial-sector templates were not sampled, so an alias falls back to heading matches when its code is absent.

### Rendering rules

- Headings become Markdown headings at their section level, in the selected label language, followed by the section
  ID in brackets so the model can cite and navigate.
- Paragraph whitespace is collapsed; bold `USERMARK` spans become bold.
- Tables become Markdown after `ROWSPAN` and `COLSPAN` are expanded into a rectangular grid. Spanned labels repeat so
  each row stands alone, and fully empty rows and columns are dropped. Numeric cells stay verbatim (commas, `-`,
  parentheses); document tables are not rescaled.
- A unit statement anywhere in a table or its caption is translated and placed above the table, for example
  `Unit: KRW million` or `Unit: KRW trillion, %`.
- Layout tables without header cells and with at most three columns (cover pages, key/value forms, KRX disclosures)
  render as `label: value` lines.
- A table larger than `max_chars` is split by rows with its header repeated, and the split is reported in `notes`.
- `IMAGE` renders as `[image not included: caption]`. Page breaks and styling are dropped, and the cover becomes a
  short header block.
- KRX pages drop `style` and `script`, use the page title as the heading, and expose a single `body` section.

### Errors

| Situation | Behavior |
| --- | --- |
| Unknown filing number (status `013`) | `ToolError` asking for the 14-digit number from `search_filings`. |
| File unavailable (status `014`) | `ToolError` with the DART viewer link. |
| Download exceeds the deadline | `ToolError`: the document is still downloading; retry in about a minute. The download continues in the background and its result is cached. |
| Archive over the size limits | `ToolError` with the observed size and the DART viewer link. |
| Unknown section | `ToolError` listing the closest outline entries. |
| `offset` past the end | Empty `content`, `next_offset: null`, and a note. |

### Download, parsing, and caching

- Use a dedicated `OpenDART` client for documents, with a 10 s connect timeout, a 90 s read timeout, and a 120 s
  overall deadline. The default client keeps its 5 s timeouts for JSON services.
- Downloads are single-flight: concurrent calls for one filing share one task. The task outlives a cancelled tool
  call, so a retry finds the result cached. The tool reports progress while it waits.
- Archive limits leave headroom over the largest sample (9.7 MB expanded): 32 MiB compressed, 32 MiB per member,
  64 MiB expanded in total, and at most 20 members. Member names are never used as paths, and nothing is written to
  disk.
- Decode UTF-8 strictly and fall back to CP949, ignoring declared charsets.
- Parse with `html.parser.HTMLParser` in a worker thread; it neither expands DTD entities nor fetches external content.
- Cache the parsed document (outline, rendered sections, and tables) by filing number. Filings are immutable, because
  corrections arrive under new filing numbers. An LRU cache bounded at 64 MiB of rendered text fits the container
  budget; outlines are small and can be kept longer.

### Resources

- `opendart://filing/{filing_number}` returns the outline result as JSON.
- `opendart://filing/{filing_number}/sections/{section_id}` returns one rendered section as `text/markdown`, unpaged,
  for hosts that attach whole sections.

### Testing

Synthetic fixtures reproduce:

- an XML prolog with unescaped `&`;
- nested sections with and without `AASSOCNOTE` and `ENG`;
- spanned tables with units, and an `EXTRACTION` table group;
- an image reference and an amendment section;
- a multi-member archive with `_00760` and `_00761`;
- a KRX key/value page, and KRX preliminary-earnings pages in both unit styles.

Golden tests cover outlines, rendering, paging boundaries, aliases, and search. An opt-in live test reads one recent
filing of each family, like the contract suite.
