"""Multi-company and filing prompts: peers, market screen, watchlist digest, filing summary."""

from typing import Final

from fastmcp.dependencies import Depends
from fastmcp.prompts import Message, prompt

from opendart_mcp.app.errors import prompt_errors
from opendart_mcp.app.state import get_state
from opendart_mcp.core.state import AppState
from opendart_mcp.prompts.common import (
    RULES,
    check_choice,
    check_window,
    check_year,
    find_filing_number,
    quoted,
    split_companies,
)

PEER_FOCUS: Final[dict[str, str]] = {
    "all": "every metric",
    "profitability": "profitability: margins, ROE, and ROA",
    "stability": "stability: debt to equity, current ratio, and interest cover",
    "growth": "growth: revenue, operating profit, and total assets",
    "activity": "activity: asset and receivables turnover",
}
"""Peer comparison focus values and the metrics they rank on."""

SCREEN_FOCUS: Final[dict[str, tuple[str, ...]]] = {
    "all": ("major_issues", "offerings", "equity_disclosures", "exchange_disclosures"),
    "dilution": ("major_issues", "offerings", "stock_options"),
    "buybacks": ("treasury_stock", "treasury_trust", "major_issues"),
    "mna": ("major_issues", "merger_offering", "merger_completion", "tender_offer"),
    "ownership": ("major_holding_report", "insider_ownership_report", "tender_offer"),
    "earnings": ("fair_disclosure", "periodic_reports"),
    "distress": ("major_issues", "market_notices"),
}
"""Filings screen focus values and the filing categories they search."""

MARKETS: Final = ("KOSPI", "KOSDAQ", "KONEX", "all")

PEERS: Final = """\
Compare {count} companies on {focus} for {year}: {names}.

1. compare_companies(companies={companies}, metrics="both", period="FY"{year_arg}).
2. For each company listed under missing, call get_financials(company=..., view="summary") and note the basis and period used.

Rank the companies on the focus metrics, explain outliers (one-off items, consolidated against separate basis, different fiscal year ends), and note differences in scale.

{rules}

Format:
| Company | Revenue | Operating margin | Net margin | ROE | Debt to equity | Revenue growth |
Then the ranking, outliers, and caveats.
"""

SCREEN: Final = """\
Screen {markets} filings since {since} for tradable events{focus}.

1. search_filings(since="{since}", categories={categories}, market=...) once per market: {calls}. Follow next_call while has_more is true; searches without a company cover at most three months.
2. Keep the filings that matter: capital raises and convertibles, buybacks, M&A, large contracts, preliminary earnings, control changes, trading halts, and distress.
3. For the kept companies, call get_corporate_events(company=..., since="{since}") for terms and dates, and read_filing for KRX disclosures without structured data.

{rules}

Format: a prioritized table, highest priority first:
| Priority | Company | Event | Key terms | Key date | Filing |
Then a one-paragraph summary.
"""

DIGEST: Final = """\
Digest what these {count} companies filed since {since}: {names}.

1. search_filings(company=..., since="{since}") for each company.
2. get_corporate_events(company=..., since="{since}") for companies with major-issue or offering filings.
3. get_corporate_action_calendar(companies={companies}, horizon="30d") for upcoming dates.
4. Use read_filing only for KRX disclosures whose titles are unclear.

{rules}

Format:
## Watchlist digest since (date)
### Requires action
Deadlines, dilution, control changes, and distress, with dates and filing numbers.
### Notable
Per company: the filing, a one-line takeaway, and the filing number.
### No new filings
Companies without filings in the window.
"""

SUMMARY: Final = """\
Summarize filing {number} in English{focus}.

1. read_filing(filing_number="{number}", mode="outline") for the sections and attachments.
2. Read the relevant sections with mode="read" and their section IDs; use mode="search" with a query to find specific terms. Continue with offset while more text remains.
3. The document is Korean: translate it, keep figures exact with their units, and give the Korean term in parentheses where a translation is uncertain.

Rules: cite section IDs and the filing number; label estimates and derived figures; OpenDART has no prices, so never estimate them.

Format:
## Title ({number}, filing date)
- What it is and who filed it
- Key numbers (table with units) and dates
- Details by section, citing section IDs
- Open questions and uncertain translations
"""


@prompt(name="peer_comparison", version="1.0.0", title="Peer comparison", tags={"workflow"})
@prompt_errors
async def peer_comparison(
    *,
    companies: str,
    fiscal_year: str = "",
    focus: str = "all",
    state: AppState = Depends(get_state),
) -> list[Message]:
    """Ranked peer table of key accounts and ratios, with commentary on outliers.

    Args:
        companies (str): Comma-separated company names, stock codes, or corporation codes.
        fiscal_year (str): Fiscal year such as 2025; blank for the latest.
        focus (str): ``all``, ``profitability``, ``stability``, ``growth``, or ``activity``.
        state (AppState): Server state, injected.

    Returns:
        list[Message]: Prompt messages containing the peer-comparison instructions.
    """
    peers = split_companies(companies)
    year = check_year(fiscal_year, state)
    chosen = check_choice("focus", focus, PEER_FOCUS)
    text = PEERS.format(
        count=len(peers),
        focus=PEER_FOCUS[chosen],
        year=f"fiscal {year}" if year else "the latest fiscal year",
        names=", ".join(peers),
        companies=quoted(peers),
        year_arg=f", fiscal_year={year}" if year else "",
        rules=RULES,
    )
    return [Message(text)]


def _markets(value: str) -> list[str]:
    """Check a comma-separated list of markets.

    Args:
        value (str): Markets such as KOSPI,KOSDAQ, or all.

    Returns:
        list[str]: Distinct markets; ``all`` alone when given.
    """
    markets = [check_choice("market", part, MARKETS) for part in value.split(",") if part.strip()]
    if not markets or "all" in markets:
        return ["all"]
    return list(dict.fromkeys(markets))


@prompt(name="filings_screen", version="1.0.0", title="Filings screen", tags={"workflow"})
@prompt_errors
async def filings_screen(
    *,
    since: str = "1d",
    market: str = "KOSPI,KOSDAQ",
    focus: str = "all",
    state: AppState = Depends(get_state),
) -> list[Message]:
    """Market-wide screen of recent filings for tradable events, prioritized with key dates.

    Args:
        since (str): Start of the window, such as ``1d``, ``7d``, or ``2026-10-01``.
        market (str): Comma-separated markets (KOSPI, KOSDAQ, KONEX), or ``all``.
        focus (str): ``all``, ``dilution``, ``buybacks``, ``mna``, ``ownership``, ``earnings``, or
            ``distress``.
        state (AppState): Server state, injected.

    Returns:
        list[Message]: Prompt messages containing the market-screen instructions.
    """
    start = check_window("since", since, state)
    markets = _markets(market)
    chosen = check_choice("focus", focus, SCREEN_FOCUS)
    text = SCREEN.format(
        markets="all" if markets == ["all"] else " and ".join(markets),
        since=start,
        focus="" if chosen == "all" else f", focusing on {chosen}",
        categories=quoted(list(SCREEN_FOCUS[chosen])),
        calls="; ".join(f"market={quoted(m)}" for m in markets),
        rules=RULES,
    )
    return [Message(text)]


@prompt(name="watchlist_digest", version="1.0.0", title="Watchlist digest", tags={"workflow"})
@prompt_errors
async def watchlist_digest(
    *,
    companies: str,
    since: str = "7d",
    state: AppState = Depends(get_state),
) -> list[Message]:
    """Digest of new filings and events across a watchlist, items needing action first.

    Args:
        companies (str): Comma-separated company names, stock codes, or corporation codes.
        since (str): Start of the window, such as ``7d`` or ``2026-10-01``.
        state (AppState): Server state, injected.

    Returns:
        list[Message]: Prompt messages containing the watchlist-digest instructions.
    """
    watchlist = split_companies(companies)
    text = DIGEST.format(
        count=len(watchlist),
        since=check_window("since", since, state),
        names=", ".join(watchlist),
        companies=quoted(watchlist),
        rules=RULES,
    )
    return [Message(text)]


@prompt(name="summarize_filing", version="1.0.0", title="Summarize a filing", tags={"workflow"})
@prompt_errors
async def summarize_filing(*, filing_number: str, focus: str = "") -> list[Message]:
    """English summary of a Korean filing with key numbers, dates, and section IDs.

    Args:
        filing_number (str): 14-digit filing number, or a DART viewer link.
        focus (str): What to concentrate on, such as issue terms; blank for everything.

    Returns:
        list[Message]: Prompt messages containing the filing-summary instructions.
    """
    number = find_filing_number(filing_number)
    topic = f", focusing on {focus.strip()}" if focus.strip() else ""
    return [Message(SUMMARY.format(number=number, focus=topic))]
