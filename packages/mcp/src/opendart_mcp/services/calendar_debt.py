"""Debt-security maturities from periodic reports, as calendar items and notes.

``debt_maturities`` is the calendar's maturity provider. Issuance records list only the
securities issued in the latest fiscal year and current period, so the items miss older
bonds still outstanding; the notes say so and give the corporate bonds due within a year
from the latest ladder, which covers every bond. Amounts are original face values; a
partly redeemed issue owes less and says so in ``redeemed``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.core.errors import QuotaExhaustedError, UpstreamError
from opendart_mcp.domain.identifiers import dart_viewer_url, is_filing_number
from opendart_mcp.domain.periods import period_end
from opendart_mcp.models.calendar import CalendarItem
from opendart_mcp.services.debt import maturity_schedule
from opendart_mcp.services.debt_tables import derive

if TYPE_CHECKING:
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.dates import DateWindow
    from opendart_mcp.models.calendar import DetailValue
    from opendart_mcp.models.debt import DebtMaturity
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.debt import MaturitySchedule

ACTION: Final = "debt_maturity"
SOURCE_KIND: Final = "debt_securities"
COVERAGE: Final = "Debt maturities list only the securities in the latest periodic reports' issuance records (issues of the latest fiscal year and current period), not older bonds still outstanding; amounts are original face values. get_debt_profile has the full maturity ladder."
"""Note on what the itemized maturities cover, added once per calendar."""


def _item(company: Company, maturity: DebtMaturity, filing_number: str) -> CalendarItem:
    """Describe one maturity as a calendar item.

    Args:
        company (Company): Resolved company.
        maturity (DebtMaturity): Maturity from the issuance record.
        filing_number (str): Periodic report listing the issue.

    Returns:
        CalendarItem: Calendar entry.
    """
    details: dict[str, DetailValue] = {
        "event": "Debt maturity",
        "instrument": maturity.instrument,
        "face_value": maturity.face_value,
        "coupon": maturity.coupon,
        "redeemed": maturity.redeemed,
        "issuer": maturity.issuer,
    }
    return CalendarItem(
        date=maturity.date,
        company=company.ref,
        action=ACTION,
        source_kind=SOURCE_KIND,
        filing_number=filing_number,
        dart_url=dart_viewer_url(filing_number),
        details={key: value for key, value in details.items() if value is not None},
    )


def _ladder_note(company: Company, schedule: MaturitySchedule) -> str | None:
    """State the corporate bonds due within a year at the latest period end.

    Args:
        company (Company): Resolved company.
        schedule (MaturitySchedule): Schedule with the corporate-bond ladder.

    Returns:
        str | None: The note, or None without a ladder.
    """
    ref, bonds = schedule.period, schedule.bonds
    if ref is None or bonds is None:
        return None
    figures = derive([bonds])
    due = round((figures.due_within_1y or 0) / 1_000_000)
    total = round((figures.total_debt_securities or 0) / 1_000_000)
    end = ref.end_date or period_end(ref.fiscal_year, ref.period, fye_month=company.fye_month)
    share = f"KRW {due:,} million" if due else "none"
    return f"{company.ref.name}: {share} of the KRW {total:,} million in corporate bonds outstanding at {end} was due within a year of that date ({ref.label} report)."


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
        schedule = await maturity_schedule(state, company, window=window)
    except QuotaExhaustedError:
        raise
    except UpstreamError as error:
        return [], [f"Debt maturities unavailable for {company.ref.name}: {error}"]
    items = [
        _item(company, maturity, maturity.filing_number)
        for maturity in schedule.maturities
        if maturity.filing_number
        and is_filing_number(maturity.filing_number)
        and window.start <= maturity.date <= window.end
    ]
    if schedule.period is None:
        return items, []
    ladder = _ladder_note(company, schedule)
    return items, [COVERAGE, *([ladder] if ladder else [])]
