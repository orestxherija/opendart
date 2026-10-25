# Governance

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.governance` reads a company's audit, board, executives, pay, and workforce from one periodic report,
and flags a modified audit opinion, going-concern language, and a change of auditor. `governance_facts` takes the
company, a `ResolvedPeriod` from [`resolve_period`](reports.md), the sections to read, a `FetchService`, and `today`.
With the data-access recipe's `sdk_filing_search` and the [extracts](extracts.md) recipe's `sdk_fetch_service`, this
reads the latest annual report's audit, board, and pay sections:

```python
import asyncio
from dataclasses import dataclass
from getpass import getpass
from pydantic import SecretStr
from opendart import OpenDART, OpenDARTSettings
from opendart_analysis.extracts import checked
from opendart_analysis.governance import governance_facts
from opendart_analysis.reports import resolve_period, today_kst


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main():
    settings = OpenDARTSettings(api_key=SecretStr(getpass("OpenDART API key: ")))
    samsung = Company(corp_code="00126380", fye_month=12)
    today = today_kst()
    async with OpenDART(settings) as client:
        resolved = await resolve_period(
            samsung,
            period="FY",
            fiscal_year=None,
            search_filings=sdk_filing_search(client),
            today=today,
        )
        facts = await governance_facts(
            samsung,
            resolved,
            sections=("audit", "board", "compensation"),
            fetch_service=sdk_fetch_service(client),
            today=today,
        )
        if facts is None:
            print("No governance tables in", checked(resolved))
            return
        audit, board, pay = facts.audit, facts.board, facts.compensation
        if audit is not None:
            print(facts.ref.label, audit.auditor, audit.opinion, audit.prior_auditor)
        if board is not None:
            print(board.directors, board.outside_directors, board.outside_director_pct)
        if pay is not None:
            print([(person.name, person.total) for person in pay.top_paid])
        for flag in facts.flags:
            print(flag.kind, flag.detail)
        print([source.filing_number for source in facts.sources])


asyncio.run(main())
```

`governance_facts` returns `GovernanceFacts`, or None when no candidate period has any requested table. It holds the
period read (`ref`), the requested `sections`, one value per section (None when not requested or not filed), the
`flags`, and the `sources` filings, titled by the resolved report. Each section reads its own services, by SDK
method name:

| Section | Value | Services |
| --- | --- | --- |
| `audit` | `AuditFacts`: auditor, opinion, emphasis, key audit matters, prior auditor and change, `fees`, `fee_scale`, `non_audit_services`, `history` | `accnut_adtor_nm_nd_adt_opinion`, `adt_servc_cncls_sttus`, `accnut_adtor_non_adt_servc_cncls_sttus` |
| `board` | `BoardFacts`: directors, outside directors and their share, appointments, dismissals, early resignations | `outcmpny_drctr_nd_change_sttus` |
| `executives` | `Executive` values, registered and unregistered, with role, term, and personal details | `exctv_sttus` |
| `compensation` | `Compensation`: approved ceiling, total and average paid, pay by director type, people paid KRW 500 million or more, the top paid, unregistered executives | four totals services, and `hmv_audit_indvdl_by_sttus_v2` and `indvdl_by_pay_v2`, each falling back to its Ver 1.0 service |
| `employees` | `Employees`: headcount, fixed-term staff, salaries, tenure, and every workforce row | `emp_sttus` |

The data rules are:

- **Amounts.** Integers in won as filed. Audit and non-audit fees are filed without a unit, so `fee_scale` infers won
  per filed unit (1, 1,000, or 1,000,000) from the fee per audit hour, near KRW 100,000; when no unit is plausible,
  `fee_scale` is None and fees stay as filed (`scale_note` explains either case in a sentence).
- **Text.** Names, titles, audit-report text, and remarks stay Korean as filed; "not applicable" placeholders become
  None. Opinions (`unqualified`, `qualified`, `adverse`, `disclaimer`), board roles, genders, and flags are English.
- **Years.** Three-year tables are aligned by their term labels (see [extracts](extracts.md)); pay tables keep the
  newest fiscal year. The audit section takes the most severe current-year opinion and keeps every distinct opinion
  row in `history`, newest first.
- **Board.** `outside_director_pct` is outside directors over directors, as a percentage with one decimal.
- **People.** Individual pay is sorted highest first. Executives keep filing order; `role` is None when unrecognized.
- **Workforce.** Totals add the headline rows (`headline`): a grand-total row, else subtotal rows such as one per
  gender, else every row. The average salary weights rows by the average headcount their totals imply, and tenure by
  headcount.
- **Flags.** Need the audit section: a modified opinion, going-concern language (계속기업) in the current year's
  opinion, emphasis, other matters, or key audit matters, and an auditor change from the prior fiscal year.
- **Values.** Every value keeps every field the report provides; choosing what to show is the caller's decision.

Upstream calls are bounded. At most `probe_attempts(resolved)` candidate periods are probed, three or fewer, and each
probe calls the requested sections' services at once: at most 12, plus a Ver 1.0 fallback for each individual-pay
service whose Ver 2.0 answer has no people. When the audit section is read and the report does not name last year's
auditor, one more call reads the prior annual report's opinion table, unless that year predates 2015. Each call
states `period_volatility` for its period. Fetch failures reach the caller unchanged, after concurrent calls finish;
`governance_facts` raises `ValueError` when `sections` is empty or names an unknown section.

The pieces are public too: `fetch_tables` fetches one period's tables, `audit_facts`, `audit_flags`, `board`,
`executives`, `compensation`, and `employees` read records, and `opinion`, `role`, `full_time`, and `fee_scale`
classify single fields.
