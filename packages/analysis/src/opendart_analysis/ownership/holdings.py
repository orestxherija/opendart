"""5% holder and insider ownership reports filed in a window.

``majorstock`` (significant holdings, the 5% rule) and ``elestock`` (executives and major
shareholders) take only the company and list about two years of filings, oldest first, with
filing dates as YYYY-MM-DD and signed changes such as ``-348,407``. Reports are kept when
filed in the window, newest first, and counted by the direction of their change.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.dates import add_months
from opendart_analysis.domain.identifiers import filing_date, is_filing_number
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date, parse_percent
from opendart_analysis.extracts import gather_all
from opendart_analysis.ownership.holding_access import HoldingQuery

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date

    from opendart_analysis.ownership.holding_access import (
        FetchInsiderHoldings,
        FetchMajorHoldings,
        InsiderHoldingRecord,
        MajorHoldingRecord,
    )
    from opendart_analysis.upstream import Volatility

LISTING_MONTHS: Final = 24
"""OpenDART lists holding reports from about the last two years only."""
VOLATILITY: Final[Volatility] = "medium"
"""Holding reports accumulate during the day but rarely change once filed."""

_MAJOR_STATUS: Final = MappingProxyType(
    {
        "10%이상주주": "Shareholders holding 10% or more",
        "사실상지배주주": "Effective controlling shareholders",
        "주요주주": "Major shareholder",
    }
)
_UNREGISTERED: Final = ("unregistered", "비등기", "미등기")
_REGISTERED: Final = ("registered", "등기")


@dataclass(frozen=True, slots=True)
class MajorHolderReport:
    """A 5% (significant holding) report; changes are signed.

    Attributes:
        filed (date | None): Filing date.
        filing_number (str): 14-digit filing number.
        reporter (str | None): Reporter.
        report_type (str | None): Report type.
        shares (int | None): Shares held.
        change_in_shares (int | None): Change in shares held.
        pct (float | None): Ownership, in percent.
        change_in_pct (float | None): Change in ownership, in percentage points.
        reason (str | None): Reasons, separated by semicolons.
        contract_shares (int | None): Shares under major contracts.
        contract_pct (float | None): Ownership under major contracts.
    """

    filed: date | None
    filing_number: str
    reporter: str | None
    report_type: str | None
    shares: int | None
    change_in_shares: int | None
    pct: float | None
    change_in_pct: float | None
    reason: str | None
    contract_shares: int | None
    contract_pct: float | None


@dataclass(frozen=True, slots=True)
class InsiderReport:
    """An ownership report of an executive or major shareholder; changes are signed.

    Attributes:
        filed (date | None): Filing date.
        filing_number (str): 14-digit filing number.
        reporter (str | None): Reporter.
        position (str | None): Position as filed.
        is_registered_officer (bool | None): Whether a registered (board) officer; None when
            not an officer or unknown.
        major_shareholder (str | None): Major-shareholder status, in English when common.
        shares (int | None): Shares held.
        change (int | None): Change in shares held.
        pct (float | None): Ownership, in percent.
        change_pct (float | None): Change in ownership, in percentage points.
    """

    filed: date | None
    filing_number: str
    reporter: str | None
    position: str | None
    is_registered_officer: bool | None
    major_shareholder: str | None
    shares: int | None
    change: int | None
    pct: float | None
    change_pct: float | None


@dataclass(frozen=True, slots=True)
class ReportActivity:
    """Counts of reports by the direction of their share change.

    Attributes:
        reports (int): Reports.
        increases (int): Reports with a positive change.
        decreases (int): Reports with a negative change.
        net_change (int): Sum of the changes.
    """

    reports: int
    increases: int
    decreases: int
    net_change: int


@dataclass(frozen=True, slots=True)
class HoldingReports:
    """Holding reports filed in a window, newest first.

    Attributes:
        since (date): First filing date, inclusive.
        until (date): Last filing date, inclusive.
        major (tuple[MajorHolderReport, ...]): 5% holder reports.
        major_activity (ReportActivity): Counts over the 5% holder reports.
        insider (tuple[InsiderReport, ...]): Insider reports.
        insider_activity (ReportActivity): Counts over the insider reports.
    """

    since: date
    until: date
    major: tuple[MajorHolderReport, ...]
    major_activity: ReportActivity
    insider: tuple[InsiderReport, ...]
    insider_activity: ReportActivity


@dataclass(slots=True)
class _Lists:
    """The company's holding reports as listed."""

    major: Sequence[MajorHoldingRecord] = ()
    insider: Sequence[InsiderHoldingRecord] = ()


async def holding_reports(
    corp_code: str,
    *,
    since: date,
    fetch_major_holdings: FetchMajorHoldings,
    fetch_insider_holdings: FetchInsiderHoldings,
    today: date,
) -> HoldingReports:
    """Read the 5% holder and insider reports filed from ``since`` to today (two calls).

    Both lists are requested concurrently with ``medium`` volatility; the first failure is
    raised unchanged after the other call finishes. Reports with a malformed filing number
    are skipped.

    Args:
        corp_code (str): 8-digit DART corporation code.
        since (date): First filing date, inclusive; see ``predates_listings``.
        fetch_major_holdings (FetchMajorHoldings): The company's 5% holder reports.
        fetch_insider_holdings (FetchInsiderHoldings): The company's insider reports.
        today (date): Today in KST, the last filing date.

    Returns:
        HoldingReports: Reports in the window, newest first, with their counts.

    Raises:
        ValueError: ``since`` is after ``today``.
    """
    if since > today:
        message = f"since ({since}) is after today ({today})."
        raise ValueError(message)
    query = HoldingQuery(corp_code)
    lists = _Lists()

    async def read_major() -> None:
        """Read the 5% holder reports."""
        lists.major = await fetch_major_holdings(query, volatility=VOLATILITY) or ()

    async def read_insider() -> None:
        """Read the insider reports."""
        lists.insider = await fetch_insider_holdings(query, volatility=VOLATILITY) or ()

    await gather_all([read_major(), read_insider()])
    major = _recent(_majors(lists.major), since, today)
    insider = _recent(_insiders(lists.insider), since, today)
    return HoldingReports(
        since=since,
        until=today,
        major=tuple(major),
        major_activity=activity(report.change_in_shares for report in major),
        insider=tuple(insider),
        insider_activity=activity(report.change for report in insider),
    )


def predates_listings(since: date, today: date) -> bool:
    """Tell whether a window starts before OpenDART's holding-report listings reach.

    Args:
        since (date): First filing date of the window.
        today (date): Today in KST.

    Returns:
        bool: True when the window starts more than ``LISTING_MONTHS`` before today.
    """
    return since < add_months(today, -LISTING_MONTHS)


def activity(changes: Iterable[int | None]) -> ReportActivity:
    """Count reports by the direction of their share change.

    Args:
        changes (Iterable[int | None]): Share change of every report; None when unknown.

    Returns:
        ReportActivity: Counts and the net change.
    """
    listed = list(changes)
    known = [change for change in listed if change]
    return ReportActivity(
        reports=len(listed),
        increases=sum(1 for change in known if change > 0),
        decreases=sum(1 for change in known if change < 0),
        net_change=sum(known),
    )


def _majors(records: Iterable[MajorHoldingRecord]) -> Iterable[MajorHolderReport]:
    """Parse 5% holder reports with a well-formed filing number.

    Args:
        records (Iterable[MajorHoldingRecord]): Upstream rows.

    Yields:
        MajorHolderReport: Report with signed changes.
    """
    for record in records:
        number = _number(record.filing_number)
        if number is None:
            continue
        yield MajorHolderReport(
            filed=parse_date(record.filing_date) or filing_date(number),
            filing_number=number,
            reporter=clean_text(record.repror),
            report_type=clean_text(record.report_tp),
            shares=parse_amount(record.stkqy),
            change_in_shares=parse_amount(record.stkqy_irds),
            pct=_pct(record.stkrt),
            change_in_pct=_pct(record.stkrt_irds),
            reason=_reason(record.report_resn),
            contract_shares=parse_amount(record.ctr_stkqy),
            contract_pct=_pct(record.ctr_stkrt),
        )


def _insiders(records: Iterable[InsiderHoldingRecord]) -> Iterable[InsiderReport]:
    """Parse insider reports with a well-formed filing number.

    Args:
        records (Iterable[InsiderHoldingRecord]): Upstream rows.

    Yields:
        InsiderReport: Report with signed changes.
    """
    for record in records:
        number = _number(record.filing_number)
        if number is None:
            continue
        yield InsiderReport(
            filed=parse_date(record.filing_date) or filing_date(number),
            filing_number=number,
            reporter=clean_text(record.repror),
            position=clean_text(record.isu_exctv_ofcps),
            is_registered_officer=_registered(record.isu_exctv_rgist_at),
            major_shareholder=_major_status(record.isu_main_shrholdr),
            shares=parse_amount(record.sp_stock_lmp_cnt),
            change=parse_amount(record.sp_stock_lmp_irds_cnt),
            pct=_pct(record.sp_stock_lmp_rate),
            change_pct=_pct(record.sp_stock_lmp_irds_rate),
        )


def _number(text: str | None) -> str | None:
    """Return a well-formed filing number.

    Args:
        text (str | None): Filing number as listed.

    Returns:
        str | None: The 14-digit number, or None when missing or malformed.
    """
    number = clean_text(text)
    return number if number is not None and is_filing_number(number) else None


def _recent[R: MajorHolderReport | InsiderReport](
    rows: Iterable[R], since: date, until: date
) -> list[R]:
    """Keep reports filed in the window, newest first.

    Args:
        rows (Iterable[R]): Parsed reports.
        since (date): First filing date.
        until (date): Last filing date.

    Returns:
        list[R]: Reports in the window; filing numbers start with the date, so they order
            reports by date and by sequence within a day.
    """
    kept = [row for row in rows if row.filed is not None and since <= row.filed <= until]
    return sorted(kept, key=lambda row: row.filing_number, reverse=True)


def _pct(text: str | None) -> float | None:
    """Parse a percentage, writing upstream's "-0.00" as 0.0.

    Args:
        text (str | None): Raw percentage.

    Returns:
        float | None: Percentage, or None for blanks and dashes.
    """
    value = parse_percent(text)
    # Adding 0.0 turns -0.0 into 0.0 and leaves every other value unchanged.
    return None if value is None else value + 0.0


def _reason(text: str | None) -> str | None:
    """Join a bulleted, multi-line reason into one line.

    Args:
        text (str | None): Reason as filed: lines such as "- 보유주식수 변동".

    Returns:
        str | None: Items separated by semicolons, or None when blank.
    """
    items = (clean_text(line.strip().lstrip("-·•")) for line in (text or "").splitlines())
    return "; ".join(item for item in items if item) or None


def _registered(text: str | None) -> bool | None:
    """Read whether an insider is a registered (board) officer.

    Args:
        text (str | None): Status as filed, such as "Unregistered executive" or 등기임원.

    Returns:
        bool | None: True for registered officers, False for unregistered ones, None when
            the reporter is not an officer or the status is blank.
    """
    folded = (clean_text(text) or "").casefold()
    if any(word in folded for word in _UNREGISTERED):
        return False
    return True if any(word in folded for word in _REGISTERED) else None


def _major_status(text: str | None) -> str | None:
    """Translate a major-shareholder status.

    Args:
        text (str | None): Status as filed, English or Korean.

    Returns:
        str | None: English status, the filed text when unknown, or None when blank.
    """
    cleaned = clean_text(text)
    return _MAJOR_STATUS.get("".join(cleaned.split()), cleaned) if cleaned else None
