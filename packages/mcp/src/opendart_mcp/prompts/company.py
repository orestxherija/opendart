"""Single-company analysis prompts: briefing, earnings review, ownership, and credit."""

from typing import Final, get_args

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.prompts import Message, prompt

from opendart_analysis.domain.types import Period
from opendart_mcp.app.errors import prompt_errors
from opendart_mcp.app.state import get_state
from opendart_mcp.core.state import AppState
from opendart_mcp.prompts.common import check_choice, check_year, subject

BRIEFING: Final = """\
Write a one-page investor briefing on {name}.

1. Read the attached profile, or call get_company_profile(company={arg}).
2. get_financials(company={arg}, view="summary") for the latest period; add view="ratios" when the fiscal year is 2022 or later.
3. get_ownership(company={arg}) for the controlling group, free float, and recent 5% holder and insider activity.
4. get_corporate_events(company={arg}, since="1y") for capital raises, convertibles, buybacks, M&A, and distress.
5. get_governance(company={arg}, sections=["audit", "board"]) for the audit opinion and board changes.
6. Use read_filing only where an item needs context.

{rules}

Format:
## {name}: briefing
- Snapshot: market, industry, fiscal year end, latest periodic report
- Financials: revenue, operating profit, net income, margins, and growth, with period-end dates
- Ownership and control
- Material events in the last year: date, event, key terms, filing number
- Governance and audit flags
- What to watch: 3-5 dated items
"""

EARNINGS: Final = """\
Review the results of {name} for {target}.

1. get_financials(company={arg}, view="summary"{period_args}) for headline accounts, margins, and growth.
2. get_financials with view="income", "balance", and "cash_flow" for the same period; pass accounts=[...] to narrow long statements.
3. For a quarter, compare with the prior quarter (QoQ) and the same quarter a year earlier (YoY). For a full year, compare with the prior year and call get_governance(company={arg}, sections=["audit"]) for the audit opinion.
4. If a newer unaudited result exists, call get_financials(company={arg}, view="preliminary") and label it preliminary.

Analyze margins, cash conversion (operating cash flow / net income), working capital, debt, and one-off items visible in the line items.

{rules}

Format:
## {name}: earnings review (period and end date)
| Line item | Current | Prior | Change |
Then margins and cash conversion, balance-sheet changes, notable line items, the audit opinion (full year only), and questions for management.
"""

OWNERSHIP: Final = """\
Assess who controls {name} and whether control is changing.

1. get_ownership(company={arg}, activity_window="1y") for the largest shareholder group, control changes, 5% holder and insider reports, treasury shares, and the free-float estimate.
2. get_corporate_events(company={arg}, categories=["capital_raise", "convertible_and_hybrid_debt", "mna_and_restructuring"], since="2y") for deals that could shift control.
3. search_filings(company={arg}, categories=["major_holding_report", "tender_offer", "proxy_solicitation"], since="1y").

{rules}

Format:
## {name}: ownership and control
- Controlling group: holder, relation, stake, change
- Control changes and 5% holder moves: dated table with filing numbers
- Insider buying and selling: net direction and notable names
- Free-float estimate, marked as an estimate
- Control risk: low, medium, or high, with reasons
"""

CREDIT: Final = """\
Write a refinancing-risk memo on {name}.

1. get_debt_profile(company={arg}) for the maturity ladder and recent issuance with coupons and ratings.
2. get_financials(company={arg}, view="balance") and view="cash_flow" for cash, borrowings, and operating cash flow; view="summary" for operating profit. Compute interest cover where interest expense is reported.
3. get_corporate_events(company={arg}, categories=["distress_and_legal", "convertible_and_hybrid_debt"], since="2y").
4. get_governance(company={arg}, sections=["audit"]) for going-concern language and emphasis of matter.

{rules}

Format:
## {name}: credit and liquidity
- Maturity ladder (table) and the share due within one year
- Liquidity: cash against short-term debt, and operating cash flow
- Recent issuance, coupons, and ratings
- Distress, legal, and audit flags
- Refinancing risk: low, medium, or high, with reasons
"""


@prompt(name="company_briefing", version="1.0.0", title="Company briefing", tags={"workflow"})
@prompt_errors
async def company_briefing(
    *,
    company: str,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> list[Message]:
    """One-page briefing on a company: profile, financials, ownership, events, and governance.

    Args:
        company (str): Company name, stock code, or DART corporation code.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        list[Message]: Prompt messages containing the briefing instructions.
    """
    target = await subject(state, ctx, company)
    return target.messages(BRIEFING.format(**target.fields))


def _period_text(period: str, year: int | None) -> tuple[str, str]:
    """Describe the requested period and the matching tool arguments.

    Args:
        period (str): Requested period.
        year (int | None): Fiscal year, or None for the latest.

    Returns:
        tuple[str, str]: Period description and extra get_financials arguments.
    """
    args = "" if period == "latest" else f', period="{period}"'
    args += f", fiscal_year={year}" if year else ""
    if period == "latest":
        latest = "the latest reported period"
        return (latest if year is None else f"{latest} of fiscal {year}"), args
    return (f"the latest {period}" if year is None else f"{period} {year}"), args


@prompt(name="earnings_review", version="1.0.0", title="Earnings review", tags={"workflow"})
@prompt_errors
async def earnings_review(
    *,
    company: str,
    fiscal_year: str = "",
    period: str = "latest",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> list[Message]:
    """Review a company's results for a period: statements, growth, margins, and cash conversion.

    Args:
        company (str): Company name, stock code, or DART corporation code.
        fiscal_year (str): Fiscal year such as 2025; blank for the latest.
        period (str): ``latest``, ``FY``, ``H1``, ``Q1``, or ``Q3``.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        list[Message]: Prompt messages containing the earnings-review instructions.
    """
    year = check_year(fiscal_year, state)
    chosen = check_choice("period", period, get_args(Period))
    target = await subject(state, ctx, company)
    described, args = _period_text(chosen, year)
    text = EARNINGS.format(**target.fields, target=described, period_args=args)
    return target.messages(text)


@prompt(
    name="ownership_and_control",
    version="1.0.0",
    title="Ownership and control",
    tags={"workflow"},
)
@prompt_errors
async def ownership_and_control(
    *,
    company: str,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> list[Message]:
    """Who controls a company, how that is changing, and the free float.

    Args:
        company (str): Company name, stock code, or DART corporation code.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        list[Message]: Prompt messages containing the ownership and control instructions.
    """
    target = await subject(state, ctx, company)
    return target.messages(OWNERSHIP.format(**target.fields))


@prompt(
    name="credit_and_liquidity",
    version="1.0.0",
    title="Credit and liquidity",
    tags={"workflow"},
)
@prompt_errors
async def credit_and_liquidity(
    *,
    company: str,
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> list[Message]:
    """Refinancing-risk memo: debt maturities, liquidity, ratings, and distress flags.

    Args:
        company (str): Company name, stock code, or DART corporation code.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        list[Message]: Prompt messages containing the credit and liquidity instructions.
    """
    target = await subject(state, ctx, company)
    return target.messages(CREDIT.format(**target.fields))
