"""Debt-security maturities from periodic reports, as calendar items and notes.

``debt_maturities`` is the calendar's maturity provider. Reading the latest periodic reports'
maturities and the corporate-bond ladder lives in ``opendart_analysis.calendar.maturities``;
this adapter binds it to the gateway and the server clock (the requests and lifetimes of
get_debt_profile), projects the items, and words the notes: issuance records list only the
securities issued in the latest fiscal year and current period, so the items miss older bonds
still outstanding, and a note gives the corporate bonds due within a year from the latest
ladder, which covers every bond. Amounts are original face values; a partly redeemed issue
owes less and says so in ``redeemed``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis import calendar
from opendart_analysis.errors import AnalysisError
from opendart_mcp.core.errors import QuotaExhaustedError, UpstreamError, from_analysis
from opendart_mcp.core.upstream import filing_search, service_fetch
from opendart_mcp.services.calendar_items import output_item, subject

if TYPE_CHECKING:
    from opendart_analysis.calendar import BondsDue, DebtMaturities
    from opendart_analysis.domain.dates import DateWindow
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.calendar import CalendarItem
    from opendart_mcp.services.companies import Company

COVERAGE: Final = "Debt maturities list only the securities in the latest periodic reports' issuance records (issues of the latest fiscal year and current period), not older bonds still outstanding; amounts are original face values. get_debt_profile has the full maturity ladder."
"""Note on what the itemized maturities cover, added once per calendar."""


def ladder_note(company: Company, bonds: BondsDue) -> str:
    """State the corporate bonds due within a year at the latest period end.

    Args:
        company (Company): Resolved company.
        bonds (BondsDue): Totals of the latest corporate-bond ladder.

    Returns:
        str: The note, in KRW million.
    """
    due = round(bonds.due_within_1y / 1_000_000)
    total = round(bonds.outstanding / 1_000_000)
    share = f"KRW {due:,} million" if due else "none"
    return f"{company.ref.name}: {share} of the KRW {total:,} million in corporate bonds outstanding at {bonds.period_end} was due within a year of that date ({bonds.period.label} report)."


async def read_maturities(state: AppState, company: Company, window: DateWindow) -> DebtMaturities:
    """Read one company's maturities through the gateway.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Calendar dates.

    Returns:
        DebtMaturities: Maturities and ladder totals.

    Raises:
        ServerError: An analysis failure, translated; gateway failures pass unchanged.
    """
    read = calendar.read_debt_maturities(
        search_filings=filing_search(state.require_gateway),
        fetch_service=service_fetch(state.require_gateway),
        today=state.today(),
    )
    try:
        return await read(subject(company), window)
    except AnalysisError as error:
        raise from_analysis(error) from error


async def debt_maturities(
    state: AppState, company: Company, window: DateWindow
) -> tuple[list[CalendarItem], list[str]]:
    """List debt maturities in a calendar window (the calendar's maturity provider).

    The debt record is optional context for the calendar: when OpenDART cannot answer for
    it, the calendar is returned without maturities and a note says why rather than
    failing. An exhausted quota still fails the call, like every other part of the calendar.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        window (DateWindow): Calendar dates to cover, the first of them possibly past.

    Returns:
        tuple[list[CalendarItem], list[str]]: Maturities inside the window, earliest first,
            and notes on their coverage; no notes when the company reports no debt tables.

    Raises:
        QuotaExhaustedError: The API key's daily quota is exhausted.
    """
    try:
        found = await read_maturities(state, company, window)
    except QuotaExhaustedError:
        raise
    except UpstreamError as error:
        return [], [f"Debt maturities unavailable for {company.ref.name}: {error}"]
    items = [output_item(item, company) for item in found.items]
    if found.period is None:
        return items, []
    ladder = [] if found.bonds is None else [ladder_note(company, found.bonds)]
    return items, [COVERAGE, *ladder]
