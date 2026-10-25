"""Debt-security maturities from periodic reports, as calendar items.

``debt_maturities`` reads ``opendart_analysis.debt.maturity_schedule`` for the latest period.
Issuance records list only the securities issued in the latest fiscal year and current
period, so the items miss older bonds still outstanding; ``BondsDue`` gives the corporate
bonds due within a year from the latest ladder, which covers every bond. Face values stay
the original amounts in won; a partly redeemed issue owes less and says so in ``redeemed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_analysis.calendar.items import DEBT_ACTION, DEBT_SOURCE_KIND, CalendarItem
from opendart_analysis.debt import derive, maturity_schedule
from opendart_analysis.domain.identifiers import is_filing_number
from opendart_analysis.domain.periods import period_end
from opendart_analysis.reports import resolve_period

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable
    from datetime import date

    from opendart_analysis.calendar.items import Detail
    from opendart_analysis.calendar.request import CalendarSubject
    from opendart_analysis.debt import Maturity, MaturitySchedule
    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.reports import FiscalCompany, PeriodRef, ResolvedPeriod
    from opendart_analysis.upstream import CallLimit, FetchService, SearchFilings


@dataclass(frozen=True, slots=True)
class BondsDue:
    """Corporate bonds outstanding at a period end, and the part due within a year.

    Attributes:
        period (PeriodRef): Period of the ladder.
        period_end (date): Last day of that period.
        due_within_1y (int): Won due within a year of the period end; 0 when none.
        outstanding (int): Won outstanding at the period end.
    """

    period: PeriodRef
    period_end: date
    due_within_1y: int
    outstanding: int


@dataclass(frozen=True, slots=True)
class DebtMaturities:
    """One company's debt maturities in a calendar window.

    Attributes:
        items (tuple[CalendarItem, ...]): Maturities in the window, earliest first, each
            citing the periodic report that lists it.
        period (PeriodRef | None): Latest period read, or None when no report had debt
            tables.
        bonds (BondsDue | None): The latest corporate-bond ladder's totals, or None without
            one.
    """

    items: tuple[CalendarItem, ...] = ()
    period: PeriodRef | None = None
    bonds: BondsDue | None = None


def maturity_item(corp_code: str, maturity: Maturity, filing_number: str) -> CalendarItem:
    """Describe one maturity as a calendar item.

    Args:
        corp_code (str): Company.
        maturity (Maturity): Maturity from the issuance record.
        filing_number (str): Periodic report listing the issue.

    Returns:
        CalendarItem: Item with action DEBT_ACTION; details without unknown values.
    """
    details: dict[str, Detail] = {
        "event": "Debt maturity",
        "instrument": maturity.instrument,
        "face_value": maturity.face_value,
        "coupon": maturity.coupon,
        "redeemed": maturity.redeemed,
        "issuer": maturity.issuer,
    }
    kept = {key: value for key, value in details.items() if value is not None}
    return CalendarItem(
        maturity.date, corp_code, DEBT_ACTION, DEBT_SOURCE_KIND, filing_number, kept
    )


def bonds_due(schedule: MaturitySchedule, *, fye_month: int) -> BondsDue | None:
    """Total the latest corporate-bond ladder.

    Args:
        schedule (MaturitySchedule): Schedule with the corporate-bond ladder.
        fye_month (int): Fiscal year-end month, for a period without a known end date.

    Returns:
        BondsDue | None: The totals, or None without a period or a ladder.
    """
    ref, bonds = schedule.period, schedule.bonds
    if ref is None or bonds is None:
        return None
    figures = derive([bonds])
    end = ref.end_date or period_end(ref.fiscal_year, ref.period, fye_month=fye_month)
    return BondsDue(ref, end, figures.due_within_1y or 0, figures.total_debt_securities or 0)


def schedule_maturities(
    corp_code: str, schedule: MaturitySchedule, window: DateWindow, *, fye_month: int
) -> DebtMaturities:
    """Turn a maturity schedule into calendar items within a window.

    Args:
        corp_code (str): Company.
        schedule (MaturitySchedule): Schedule from ``opendart_analysis.debt``.
        window (DateWindow): Calendar dates to keep.
        fye_month (int): Fiscal year-end month.

    Returns:
        DebtMaturities: Maturities that cite a valid filing number, within the window.
    """
    items = tuple(
        maturity_item(corp_code, maturity, maturity.filing_number)
        for maturity in schedule.maturities
        if maturity.filing_number
        and is_filing_number(maturity.filing_number)
        and window.start <= maturity.date <= window.end
    )
    return DebtMaturities(items, schedule.period, bonds_due(schedule, fye_month=fye_month))


async def debt_maturities(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    window: DateWindow,
    names: Iterable[str | None],
    fetch_service: FetchService,
    today: date,
) -> DebtMaturities:
    """List a company's debt maturities in a calendar window, with its bond ladder totals.

    Args:
        company (FiscalCompany): Company.
        resolved (ResolvedPeriod): Candidates for the latest period, from
            ``resolve_period(company, period="latest", ...)``.
        window (DateWindow): Calendar dates, the first of them possibly past.
        names (Iterable[str | None]): The company's names, to tell its own issues from
            those of subsidiaries.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        DebtMaturities: Maturities and ladder totals; empty when no report has debt tables.
    """
    schedule = await maturity_schedule(
        company, resolved, window=window, names=names, fetch_service=fetch_service, today=today
    )
    return schedule_maturities(company.corp_code, schedule, window, fye_month=company.fye_month)


def read_debt_maturities(
    *,
    search_filings: SearchFilings,
    fetch_service: FetchService,
    today: date,
    limit: CallLimit | None = None,
) -> Callable[[CalendarSubject, DateWindow], Awaitable[DebtMaturities]]:
    """Bind ``debt_maturities`` to data access, resolving each company's latest period.

    The reader's calls are not bounded by the calendar's limit unless they share it: pass
    the ``CallLimit`` given to ``corporate_action_calendar``, or bound the callables
    yourself.

    Args:
        search_filings (SearchFilings): Filing search for ``resolve_period``; a leaf
            callable, wrapped in ``limit`` when given.
        fetch_service (FetchService): Service calls for the debt tables; a leaf callable,
            wrapped in ``limit`` when given.
        today (date): Today in KST.
        limit (CallLimit | None): Bound shared with other callables, such as the
            calendar's; None leaves the bound to the callables. Defaults to None.

    Returns:
        Callable[[CalendarSubject, DateWindow], Awaitable[DebtMaturities]]: A maturity
            reader for ``corporate_action_calendar``.
    """
    if limit is not None:
        search_filings = limit.bound(search_filings)
        fetch_service = limit.bound(fetch_service)

    async def read(subject: CalendarSubject, window: DateWindow) -> DebtMaturities:
        """Read one company's debt maturities.

        Args:
            subject (CalendarSubject): Company.
            window (DateWindow): Calendar dates.

        Returns:
            DebtMaturities: Maturities and ladder totals.
        """
        resolved = await resolve_period(
            subject, period="latest", fiscal_year=None, search_filings=search_filings, today=today
        )
        return await debt_maturities(
            subject,
            resolved,
            window=window,
            names=subject.names,
            fetch_service=fetch_service,
            today=today,
        )

    return read
