"""Reporting periods, report codes, periodic-report titles, and "latest" candidates.

OpenDART's periodic data takes a fiscal year (``bsns_year``) and a report code: 11011
annual (FY), 11012 half-year (H1), 11013 first quarter (Q1), 11014 third quarter (Q3).
Data starts with fiscal 2015 (financial indicators with 2022). Annual reports are due 90
days after the fiscal year ends, half-year and quarterly reports 45 days after the period
ends.

Fiscal-year labels: this module labels a fiscal year by the calendar year in which it ends.
How OpenDART labels ``bsns_year`` for non-December year ends is unverified, so functions
that turn a filing into a fiscal year return both candidate labels for those companies,
end-year label first; every candidate carries the period's actual end date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from opendart_analysis.domain.dates import add_months, month_end
from opendart_analysis.domain.filings import amendment_marker, clean_title

if TYPE_CHECKING:
    from collections.abc import Mapping

    from opendart_analysis.domain.types import ConcretePeriod, Period, ReportCode

PeriodicKind = Literal["annual", "semiannual", "quarterly"]
"""Kind of periodic report named in a filing title."""

REPORT_CODES: Mapping[ConcretePeriod, ReportCode] = MappingProxyType(
    {"FY": "11011", "H1": "11012", "Q1": "11013", "Q3": "11014"}
)
"""Upstream report code per period."""

PERIODS_BY_REPORT_CODE: Mapping[ReportCode, ConcretePeriod] = MappingProxyType(
    {code: period for period, code in REPORT_CODES.items()}
)
"""Period per upstream report code."""

PERIOD_LABELS: Mapping[ConcretePeriod, str] = MappingProxyType(
    {"FY": "annual", "H1": "half-year", "Q1": "first quarter", "Q3": "third quarter"}
)
"""Plain-English name of each period."""

FILING_DEADLINE_DAYS: Mapping[ConcretePeriod, int] = MappingProxyType(
    {"FY": 90, "H1": 45, "Q1": 45, "Q3": 45}
)
"""Statutory days from the period end to the report deadline."""

FIRST_FISCAL_YEAR = 2015
"""First fiscal year with periodic-report data in OpenDART."""

FIRST_INDICATOR_YEAR = 2022
"""First fiscal year with financial indicators (``fnltt_singl_indx``)."""

# Months from the end of each period to the end of its fiscal year.
_MONTHS_TO_YEAR_END: Mapping[ConcretePeriod, int] = MappingProxyType(
    {"FY": 0, "Q3": 3, "H1": 6, "Q1": 9}
)
_PERIOD_BY_OFFSET: Mapping[int, ConcretePeriod] = MappingProxyType(
    {0: "FY", 9: "Q3", 6: "H1", 3: "Q1"}
)
_KINDS: Mapping[ConcretePeriod, PeriodicKind] = MappingProxyType(
    {"FY": "annual", "H1": "semiannual", "Q1": "quarterly", "Q3": "quarterly"}
)
_TITLE = re.compile(
    r"""
    (?P<kind>semi-?\s*annual|half-?\s*year(?:ly)?|annual|business|quarterly|quarter|사업|반기|분기)
    \s*(?:report|보고서)
    \s*\(\s*(?P<year>[0-9]{4})\s*[./-]\s*(?P<month>[0-9]{1,2})\s*\)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_LEADING_MARKERS = re.compile(r"^(?:\[[^\]]*\]\s*)+")
_MONTHS = range(1, 13)
DECEMBER = 12
"""The most common fiscal year-end month, assumed when a company states none."""


@dataclass(frozen=True, slots=True)
class PeriodRef:
    """A fiscal year and period, as OpenDART's ``bsns_year`` and ``reprt_code`` expect.

    Attributes:
        fiscal_year (int): Fiscal-year label passed as ``bsns_year``.
        period (ConcretePeriod): Reporting period.
        end_date (date | None): Calendar end of the period when known; ignored by equality
            and hashing.
    """

    fiscal_year: int
    period: ConcretePeriod
    end_date: date | None = field(default=None, compare=False)

    @property
    def report_code(self) -> ReportCode:
        """Upstream report code.

        Returns:
            ReportCode: ``11011``, ``11012``, ``11013``, or ``11014``.
        """
        return REPORT_CODES[self.period]

    @property
    def label(self) -> str:
        """Short label such as ``FY2025`` or ``Q3 2025``.

        Returns:
            str: Display label.
        """
        return (
            f"FY{self.fiscal_year}" if self.period == "FY" else f"{self.period} {self.fiscal_year}"
        )


@dataclass(frozen=True, slots=True)
class PeriodicTitle:
    """A parsed periodic-report title such as ``Annual Report (2025.12)``.

    Attributes:
        kind (PeriodicKind): Annual, semiannual, or quarterly report.
        year (int): Calendar year of the period end.
        month (int): Month of the period end.
        amendment (str | None): Leading amendment marker, such as ``Revision of statements``.
    """

    kind: PeriodicKind
    year: int
    month: int
    amendment: str | None


def period_end(fiscal_year: int, period: ConcretePeriod, *, fye_month: int = 12) -> date:
    """Return the last day of a period, labeling fiscal years by the year they end.

    Args:
        fiscal_year (int): Calendar year in which the fiscal year ends.
        period (ConcretePeriod): Reporting period.
        fye_month (int): Fiscal year-end month, 1 to 12 (the profile's ``acc_mt``).

    Returns:
        date: Period end, for example 2025-09-30 for Q3 2025 with a December year end.

    Raises:
        ValueError: fye_month is not between 1 and 12.
    """
    _check_month(fye_month)
    start = add_months(date(fiscal_year, fye_month, 1), -_MONTHS_TO_YEAR_END[period])
    return month_end(start.year, start.month)


def filing_deadline(fiscal_year: int, period: ConcretePeriod, *, fye_month: int = 12) -> date:
    """Return the statutory deadline of a periodic report.

    Args:
        fiscal_year (int): Calendar year in which the fiscal year ends.
        period (ConcretePeriod): Reporting period.
        fye_month (int): Fiscal year-end month, 1 to 12.

    Returns:
        date: Period end plus 90 days (FY) or 45 days (H1, Q1, Q3).

    Raises:
        ValueError: fye_month is not between 1 and 12.
    """
    end = period_end(fiscal_year, period, fye_month=fye_month)
    return end + timedelta(days=FILING_DEADLINE_DAYS[period])


def parse_periodic_title(title: str) -> PeriodicTitle | None:
    """Parse a periodic-report title from search results.

    Accepts English titles (``Annual Report (2025.12)``, ``Semi-Annual Report (2026.06)``,
    ``Quarterly Report (2026.03)``, also "Business Report" and "Half-Year Report") and
    Korean ones (``사업보고서 (2025.12)``, ``반기보고서``, ``분기보고서``), in any case, with
    leading amendment markers such as ``[Revision of statements]`` and padding spaces.

    Args:
        title (str): Report title.

    Returns:
        PeriodicTitle | None: Parsed title, or None for other reports or invalid months.
    """
    cleaned = clean_title(title)
    match = _TITLE.fullmatch(_LEADING_MARKERS.sub("", cleaned))
    if match is None or int(match["month"]) not in _MONTHS:
        return None
    word = match["kind"].lower()
    kind: PeriodicKind
    if word.startswith(("semi", "half", "반기")):
        kind = "semiannual"
    elif word.startswith(("quarter", "분기")):
        kind = "quarterly"
    else:
        kind = "annual"
    return PeriodicTitle(kind, int(match["year"]), int(match["month"]), amendment_marker(cleaned))


def period_from_title(parsed: PeriodicTitle, *, fye_month: int = 12) -> tuple[PeriodRef, ...]:
    """Map a parsed title to the fiscal year and period to request.

    With a December year end the answer is unique. Otherwise two labels are returned, the
    year the fiscal year ends first and the year it starts second, because OpenDART's label
    for such companies is unverified.

    Args:
        parsed (PeriodicTitle): Parsed title.
        fye_month (int): Fiscal year-end month, 1 to 12.

    Returns:
        tuple[PeriodRef, ...]: Candidates in probing order; empty when the title's month and
            kind do not fit the fiscal year end (for example a quarterly report ending in
            the year-end month).

    Raises:
        ValueError: fye_month is not between 1 and 12.
    """
    _check_month(fye_month)
    offset = (parsed.month - fye_month) % 12
    period = _PERIOD_BY_OFFSET.get(offset)
    if period is None or _KINDS[period] != parsed.kind:
        return ()
    year_end = add_months(date(parsed.year, parsed.month, 1), (12 - offset) % 12)
    end = month_end(parsed.year, parsed.month)
    return _labels(year_end.year, period, end, fye_month=fye_month)


def latest_candidates(
    *,
    today: date,
    period: Period,
    fiscal_year: int | None,
    fye_month: int = 12,
    depth: int = 6,
) -> tuple[PeriodRef, ...]:
    """List the periods most likely to have the newest report, newest first.

    Used as a probing fallback when the filing index does not settle "latest". Periods that
    ended before today are listed by end date, newest first, so a period still inside its
    filing window (Q3 between September 30 and November 14) comes first and the most recent
    period already past its deadline follows. Periods before fiscal 2015 are omitted.

    Args:
        today (date): Today in KST.
        period (Period): ``latest`` for any period, or one period kind.
        fiscal_year (int | None): Restrict to one fiscal-year label.
        fye_month (int): Fiscal year-end month, 1 to 12.
        depth (int): Maximum number of candidates.

    Returns:
        tuple[PeriodRef, ...]: Candidates, newest first; with a non-December year end, each
            period appears under both fiscal-year labels.

    Raises:
        ValueError: fye_month is not between 1 and 12.
    """
    _check_month(fye_month)
    candidates: list[PeriodRef] = []
    end = _last_quarter_end(today - timedelta(days=1), fye_month)
    while len(candidates) < depth and end.year >= FIRST_FISCAL_YEAR - 1:
        offset = (end.month - fye_month) % 12
        kind = _PERIOD_BY_OFFSET[offset]
        year_end = add_months(end, (12 - offset) % 12).year
        refs = _labels(year_end, kind, end, fye_month=fye_month)
        candidates.extend(
            ref
            for ref in refs
            if period in {"latest", kind}
            and fiscal_year in {None, ref.fiscal_year}
            and ref.fiscal_year >= FIRST_FISCAL_YEAR
        )
        end = month_end(*_year_month(add_months(end, -3)))
    return tuple(candidates[:depth])


def fiscal_years_back(ref: PeriodRef, years: int, *, step: int = 1) -> tuple[PeriodRef, ...]:
    """List the same period in earlier fiscal years for multi-year chains, newest first.

    One annual financial-statement call already returns the current, prior, and two-years-
    prior columns (quarterly calls: current and prior year), so a caller wanting more years
    can pass ``step=3`` for annual reports and request every third fiscal year.

    Args:
        ref (PeriodRef): Newest period.
        years (int): Number of periods to return, at least 1.
        step (int): Fiscal years between consecutive periods, at least 1.

    Returns:
        tuple[PeriodRef, ...]: ``ref`` and earlier periods, stopping at fiscal 2015; end
            dates shift with the year when ``ref`` has one.

    Raises:
        ValueError: years or step is less than 1.
    """
    if years < 1 or step < 1:
        msg = f"years and step must be at least 1, got years={years} and step={step}"
        raise ValueError(msg)
    refs: list[PeriodRef] = []
    for back in range(0, years * step, step):
        if ref.fiscal_year - back < FIRST_FISCAL_YEAR:
            break
        end = ref.end_date
        shifted = None if end is None else month_end(*_year_month(add_months(end, -12 * back)))
        refs.append(PeriodRef(ref.fiscal_year - back, ref.period, end_date=shifted))
    return tuple(refs)


def _labels(
    year_end: int, period: ConcretePeriod, end: date, *, fye_month: int
) -> tuple[PeriodRef, ...]:
    """Build the fiscal-year label candidates for one period.

    Args:
        year_end (int): Calendar year in which the fiscal year ends.
        period (ConcretePeriod): Reporting period.
        end (date): Period end.
        fye_month (int): Fiscal year-end month.

    Returns:
        tuple[PeriodRef, ...]: One candidate for December year ends, otherwise the end-year
            label then the start-year label.
    """
    primary = PeriodRef(year_end, period, end_date=end)
    if fye_month == DECEMBER:
        return (primary,)
    return primary, PeriodRef(year_end - 1, period, end_date=end)


def _last_quarter_end(day: date, fye_month: int) -> date:
    """Find the latest fiscal quarter end on or before a day.

    Args:
        day (date): Latest allowed date.
        fye_month (int): Fiscal year-end month.

    Returns:
        date: Month end of the latest quarter boundary.
    """
    months_since = (day.month - fye_month) % 3
    candidate = add_months(date(day.year, day.month, 1), -months_since)
    end = month_end(candidate.year, candidate.month)
    if end > day:
        shifted = add_months(candidate, -3)
        end = month_end(shifted.year, shifted.month)
    return end


def _year_month(value: date) -> tuple[int, int]:
    """Split a date into year and month.

    Args:
        value (date): Date.

    Returns:
        tuple[int, int]: Year and month.
    """
    return value.year, value.month


def _check_month(fye_month: int) -> None:
    """Validate a fiscal year-end month.

    Args:
        fye_month (int): Month to check.

    Raises:
        ValueError: The month is not between 1 and 12.
    """
    if fye_month not in _MONTHS:
        msg = f"fye_month must be between 1 and 12, got {fye_month}"
        raise ValueError(msg)
