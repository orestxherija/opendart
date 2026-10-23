"""Event-driven prompts: event impact, dilution overhang, and the pre-trade checklist."""

from typing import Final

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.prompts import Message, prompt

from opendart_mcp.app.errors import prompt_errors
from opendart_mcp.app.state import get_state
from opendart_mcp.core.state import AppState
from opendart_mcp.prompts.common import (
    check_choice,
    check_price,
    check_window,
    find_filing_number,
    quoted,
    subject,
)
from opendart_mcp.registry import EVENT_GROUPS, EVENT_KINDS

DIRECTIONS: Final = ("long", "short")
GROUP_OF: Final[dict[str, str]] = {
    **{kind: spec.group for kind, spec in EVENT_KINDS.items()},
    **{group: group for group in EVENT_GROUPS},
}
"""The event group of each kind and group name."""

IMPACT: Final = """\
Assess the impact of {event} at {name}.

1. {locate}
2. Extract the terms: amounts, prices, share counts, rates, counterparties, conditions, and dates.
3. get_capital_structure(company={arg}, sections=["shares"]) and get_financials(company={arg}, view="summary"). Compute the dilution (new shares / shares outstanding) or the leverage effect (new debt against equity and total assets), showing the arithmetic.
4. get_corporate_events(company={arg}{precedents}, since="5y") for earlier similar events and how they were sized.

{rules}

Format:
## Event impact: {name}
- Event and terms: table with the filing number
- Dilution or leverage effect
- Key dates: board decision, subscription, payment, listing, conversion window
- Precedents at this company
- Assessment and what to monitor
"""

DILUTION: Final = """\
Inventory the potential dilution at {name} from the last {lookback}.

1. get_corporate_events(company={arg}, categories=["convertible_and_hybrid_debt", "capital_raise"], since="{lookback}") for convertible, warrant, and exchangeable bonds and share issues.
2. get_capital_structure(company={arg}, sections=["shares", "treasury_stock", "capital_changes"]) for shares outstanding, treasury shares, and conversions already made.
3. search_filings(company={arg}, categories=["stock_options", "treasury_stock"], since="{lookback}") for option grants and treasury share disposals.
4. read_filing for refixing (price reset) floors and conversion windows that step 1 lacks.

Compute the potential new shares per instrument and in total, as a percentage of shares outstanding. {price}

{rules}

Format:
| Instrument | Filing | Issued | Amount | Conversion price | Floor | Window | Potential shares | % of outstanding |
Then the total overhang, near-term conversion risk, and dates to watch.
"""

CHECKLIST: Final = """\
Run a pre-trade checklist on {name} for a {direction} position over {horizon}.

1. get_corporate_action_calendar(companies=[{arg}], horizon="{horizon}") for dated events in the horizon.
2. get_corporate_events(company={arg}, categories=["convertible_and_hybrid_debt", "capital_raise"], since="2y") and get_capital_structure(company={arg}) for dilution overhang.
3. get_ownership(company={arg}, activity_window="180d") for control changes and 5% holder or insider selling.
4. get_governance(company={arg}, sections=["audit", "board"]) for the audit opinion, going-concern language, and auditor changes.
5. get_corporate_events(company={arg}, categories=["distress_and_legal"], since="2y") for defaults, lawsuits, and suspensions.
6. search_filings(company={arg}, since="90d", final_only=false) for recent amendments.

{side}{rules}

Format:
| Check | PASS or FLAG | Evidence (date, filing number) |
Checks: upcoming dates, dilution, ownership changes, governance and audit, distress and legal, amendments{extra}. End with an overall verdict and the dates to watch.
"""

_SHORT_SIDE: Final = "For a short position, also flag buybacks, treasury-stock trusts, and tender offers, which support the price.\n\n"
_PRICE_GIVEN: Final = "Compare each conversion price and floor with the user's share price of KRW {price}, flag instruments that are in the money, and use no other price."
_NO_PRICE: Final = "No share price was given: report conversion prices and floors without judging whether they are in the money, and do not estimate a price."


def event_category(event: str) -> str | None:
    """Recognize an event kind or group name, ignoring case, spaces, and hyphens.

    Args:
        event (str): Event description.

    Returns:
        str | None: The kind or group name, or None for free text.
    """
    key = event.strip().casefold().replace(" ", "_").replace("-", "_")
    return key if key in GROUP_OF else None


def _event_terms(arg: str, event: str, number: str | None) -> dict[str, str]:
    """Describe the event, how to find it, and where to look for precedents.

    Args:
        arg (str): Company argument as a JSON literal.
        event (str): Event kind, group, free text, or blank.
        number (str | None): Filing number, when given.

    Returns:
        dict[str, str]: Template fields ``event``, ``locate``, and ``precedents``.
    """
    category = event_category(event)
    precedents = f", categories={quoted([GROUP_OF[category]])}" if category else ""
    search = f'get_corporate_events(company={arg}, since="1y")'
    if number is not None:
        described = f"the event in filing {number}"
        locate = f'read_filing(filing_number="{number}", mode="outline"), then read the sections that state the terms.'
    elif category is not None:
        described = f"the latest {category.replace("_", " ")} event"
        locate = f'get_corporate_events(company={arg}, categories={quoted([category])}, since="1y") and take the most recent event.'
    elif event.strip():
        described = quoted(event.strip())
        locate = f"{search} and find the event matching {described}; use search_filings and read_filing if it has no structured data."
    else:
        described = "its most recent material event"
        locate = f"{search} and take the most recent material event."
    return {"event": described, "locate": locate, "precedents": precedents}


@prompt(name="event_impact", version="1.0.0", title="Event impact", tags={"workflow"})
@prompt_errors
async def event_impact(
    *,
    company: str,
    event: str = "",
    filing_number: str = "",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> list[Message]:
    """Impact memo on one corporate event: terms, dilution or leverage, dates, and precedents.

    Args:
        company (str): Company name, stock code, or DART corporation code.
        event (str): Event kind or group such as ``convertible_bond``, or a short description.
        filing_number (str): Filing number of the event, if known.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        list[Message]: Prompt messages containing the event-impact instructions.
    """
    number = find_filing_number(filing_number) if filing_number.strip() else None
    target = await subject(state, ctx, company)
    terms = _event_terms(target.fields["arg"], event, number)
    return target.messages(IMPACT.format(**target.fields, **terms))


@prompt(name="dilution_overhang", version="1.0.0", title="Dilution overhang", tags={"workflow"})
@prompt_errors
async def dilution_overhang(
    *,
    company: str,
    lookback: str = "3y",
    share_price: str = "",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> list[Message]:
    """Inventory convertibles, rights issues, options, and treasury disposals against shares out.

    Args:
        company (str): Company name, stock code, or DART corporation code.
        lookback (str): How far back to look, such as ``3y`` or ``2023-01-01``.
        share_price (str): Current share price in won, if known; it is never estimated.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        list[Message]: Prompt messages containing the dilution-overhang instructions.
    """
    window = check_window("lookback", lookback, state)
    price = check_price(share_price)
    target = await subject(state, ctx, company)
    note = _PRICE_GIVEN.format(price=price) if price else _NO_PRICE
    return target.messages(DILUTION.format(**target.fields, lookback=window, price=note))


@prompt(name="pre_trade_checklist", version="1.0.0", title="Pre-trade checklist", tags={"workflow"})
@prompt_errors
async def pre_trade_checklist(
    *,
    company: str,
    direction: str = "long",
    horizon: str = "3m",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> list[Message]:
    """Pass/flag checklist before a trade: dates, dilution, ownership, audit, distress, amendments.

    Args:
        company (str): Company name, stock code, or DART corporation code.
        direction (str): ``long`` or ``short``.
        horizon (str): Holding period ahead, such as ``3m`` or ``2026-12-31``.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        list[Message]: Prompt messages containing the pre-trade checklist instructions.
    """
    side = check_choice("direction", direction, DIRECTIONS)
    ahead = check_window("horizon", horizon, state, forward=True)
    target = await subject(state, ctx, company)
    short = side == "short"
    text = CHECKLIST.format(
        **target.fields,
        direction=side,
        horizon=ahead,
        side=_SHORT_SIDE if short else "",
        extra=", price support" if short else "",
    )
    return target.messages(text)
