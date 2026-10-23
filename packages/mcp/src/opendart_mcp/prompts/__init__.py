"""Analyst workflow prompts.

Prompt modules omit ``from __future__ import annotations``: FastMCP appends a JSON-schema
note to every argument whose annotation is not the ``str`` object.
"""

from opendart_mcp.prompts.company import (
    company_briefing,
    credit_and_liquidity,
    earnings_review,
    ownership_and_control,
)
from opendart_mcp.prompts.events import dilution_overhang, event_impact, pre_trade_checklist
from opendart_mcp.prompts.market import (
    filings_screen,
    peer_comparison,
    summarize_filing,
    watchlist_digest,
)

PROMPTS = (
    company_briefing,
    earnings_review,
    event_impact,
    dilution_overhang,
    ownership_and_control,
    credit_and_liquidity,
    peer_comparison,
    filings_screen,
    pre_trade_checklist,
    watchlist_digest,
    summarize_filing,
)
"""Every prompt, in the component design's order."""
