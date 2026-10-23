"""Dates in Korea Standard Time, date arguments, and filing-search windows.

OpenDART dates are Korean calendar dates, and its daily quota resets at midnight KST, so
"today" always means today in Seoul. Arguments accept ISO dates or relative durations;
month and year arithmetic clamps the day to the target month's length.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import MAXYEAR, MINYEAR, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from datetime import tzinfo


def _korea() -> tzinfo:
    """Load Asia/Seoul, falling back to a fixed UTC+9 offset without a zone database.

    Korea has not observed daylight saving time since 1988, so the fixed offset gives the
    same results for any date OpenDART serves.

    Returns:
        tzinfo: Korea Standard Time.
    """
    try:
        return ZoneInfo("Asia/Seoul")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=9), "KST")


KST: tzinfo = _korea()
"""Korea Standard Time (``ZoneInfo("Asia/Seoul")`` when the zone database is available)."""

_DATE_HELP = (
    "use an ISO date such as 2025-01-01, 'today', 'ytd', or a duration such as 30d, 2w, 6m, or 2y"
)
_HORIZON_HELP = (
    "use an ISO date such as 2025-12-31, 'today', or a duration such as 30d, 2w, 6m, or 2y"
)
_COMPACT_DATE = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})")
_SEPARATED_DATE = re.compile(r"([0-9]{4})([-./])([0-9]{1,2})\2([0-9]{1,2})\.?")
_DURATION = re.compile(r"([0-9]{1,5})\s*(d|days?|w|weeks?|m|months?|y|years?)")
_MAX_DURATION_DAYS = 100 * 366


@dataclass(frozen=True, slots=True)
class DateWindow:
    """An inclusive range of calendar dates.

    Attributes:
        start (date): First day.
        end (date): Last day, not before start.

    Raises:
        ValueError: start is after end.
    """

    start: date
    end: date

    def __post_init__(self) -> None:
        """Validate the order of the bounds.

        Raises:
            ValueError: start is after end.
        """
        if self.start > self.end:
            msg = f"The window starts ({self.start}) after it ends ({self.end})"
            raise ValueError(msg)

    @property
    def days(self) -> int:
        """Count the days in the window, both ends included.

        Returns:
            int: Number of calendar days.
        """
        return (self.end - self.start).days + 1


def today_kst(now: datetime | None = None) -> date:
    """Return today's date in Korea.

    Args:
        now (datetime | None): Aware current time; defaults to the system clock.

    Returns:
        date: Calendar date in KST.

    Raises:
        ValueError: now is naive.
    """
    moment = datetime.now(KST) if now is None else now
    if moment.utcoffset() is None:
        msg = "now must be timezone-aware"
        raise ValueError(msg)
    return moment.astimezone(KST).date()


def add_months(value: date, months: int) -> date:
    """Shift a date by whole months, clamping the day to the target month's length.

    Args:
        value (date): Starting date.
        months (int): Months to add; negative values go back.

    Returns:
        date: Shifted date, for example 2025-03-31 minus one month is 2025-02-28.

    Raises:
        ValueError: The result is outside the supported year range.
    """
    year, month = divmod(value.year * 12 + value.month - 1 + months, 12)
    if not MINYEAR <= year <= MAXYEAR:
        msg = f"Date out of range: {months} months from {value}"
        raise ValueError(msg)
    return date(year, month + 1, min(value.day, calendar.monthrange(year, month + 1)[1]))


def month_end(year: int, month: int) -> date:
    """Return the last day of a month.

    Args:
        year (int): Calendar year.
        month (int): Month, 1 to 12.

    Returns:
        date: Last day of the month.
    """
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_date_arg(text: str, *, today: date) -> date:
    """Parse a date argument that may count backwards from today.

    Accepts ISO ``2025-01-01``, ``20250101``, ``2025.01.01``, ``2025/1/5``, ``today``,
    ``yesterday``, ``ytd`` (January 1 of today's year), and durations back from today:
    ``30d``, ``2w``, ``6m``, ``2y`` (also spelled out, such as ``6 months``).

    Args:
        text (str): Date argument.
        today (date): Reference date for relative values.

    Returns:
        date: Parsed date.

    Raises:
        ValueError: The text is not a supported form or the date is invalid.
    """
    keyword = text.strip().lower()
    keywords = {
        "today": today,
        "yesterday": today - timedelta(days=1),
        "ytd": date(today.year, 1, 1),
    }
    if keyword in keywords:
        return keywords[keyword]
    return _parse(text, today=today, sign=-1, help_text=_DATE_HELP)


def parse_horizon(text: str, *, today: date) -> date:
    """Parse a forward-looking date argument, such as a calendar horizon.

    Accepts the absolute forms of ``parse_date_arg``, ``today``, and durations forward from
    today: ``30d``, ``2w``, ``6m``, ``2y``.

    Args:
        text (str): Horizon argument.
        today (date): Reference date for relative values.

    Returns:
        date: Parsed date.

    Raises:
        ValueError: The text is not a supported form or the date is invalid.
    """
    if text.strip().lower() == "today":
        return today
    return _parse(text, today=today, sign=1, help_text=_HORIZON_HELP)


def _parse(text: str, *, today: date, sign: int, help_text: str) -> date:
    """Parse an absolute date or a duration applied in one direction.

    Args:
        text (str): Date argument.
        today (date): Reference date.
        sign (int): -1 to count back, 1 to count forward.
        help_text (str): Accepted forms, for the error message.

    Returns:
        date: Parsed date.

    Raises:
        ValueError: The text is not a supported form or the date is invalid.
    """
    cleaned = text.strip().lower()
    try:
        parsed = _absolute(cleaned)
        if parsed is None:
            parsed = _relative(cleaned, today=today, sign=sign)
    except (ValueError, OverflowError) as error:
        msg = f"Invalid date {text!r}: {error}; {help_text}"
        raise ValueError(msg) from error
    if parsed is None:
        msg = f"Invalid date {text!r}; {help_text}"
        raise ValueError(msg)
    return parsed


def _absolute(text: str) -> date | None:
    """Parse an absolute date.

    Args:
        text (str): Lowercase, stripped argument.

    Returns:
        date | None: The date, or None when the text is not an absolute form.

    Raises:
        ValueError: The text has a date shape but is not a valid date.
    """
    if match := _COMPACT_DATE.fullmatch(text):
        year, month, day = match.groups()
    elif match := _SEPARATED_DATE.fullmatch(text):
        year, _, month, day = match.groups()
    else:
        return None
    return date(int(year), int(month), int(day))


def _relative(text: str, *, today: date, sign: int) -> date | None:
    """Apply a duration such as ``30d`` or ``6m`` to today.

    Args:
        text (str): Lowercase, stripped argument.
        today (date): Reference date.
        sign (int): -1 to count back, 1 to count forward.

    Returns:
        date | None: Shifted date, or None when the text is not a duration.

    Raises:
        ValueError: The duration is longer than a hundred years.
    """
    match = _DURATION.fullmatch(text)
    if match is None:
        return None
    amount, unit = int(match.group(1)), match.group(2)[0]
    if amount * {"d": 1, "w": 7, "m": 31, "y": 366}[unit] > _MAX_DURATION_DAYS:
        msg = "durations are limited to 100 years"
        raise ValueError(msg)
    if unit in {"d", "w"}:
        return today + timedelta(days=sign * amount * (7 if unit == "w" else 1))
    return add_months(today, sign * amount * (12 if unit == "y" else 1))


def resolve_window(
    since: str | None, until: str | None, *, today: date, default_since: str
) -> DateWindow:
    """Resolve ``since``/``until`` arguments into a date window.

    ``until`` defaults to today. Relative ``since`` values (and ``default_since``) count back
    from ``until``, so ``since="90d", until="2024-12-31"`` covers the 90 days before that
    date; relative ``until`` values count back from today.

    Args:
        since (str | None): Window start, or None for default_since.
        until (str | None): Window end, or None for today.
        today (date): Today in KST.
        default_since (str): Start used when since is None, such as ``90d``.

    Returns:
        DateWindow: The window.

    Raises:
        ValueError: An argument is invalid or the start is after the end.
    """
    end = today if until is None else parse_date_arg(until, today=today)
    start = parse_date_arg(default_since if since is None else since, today=end)
    if start > end:
        msg = f"since ({start.isoformat()}) is after until ({end.isoformat()}); pass an earlier since or a later until"
        raise ValueError(msg)
    return DateWindow(start, end)


def within_three_months(window: DateWindow) -> bool:
    """Check OpenDART's limit for filing searches without a company.

    The window may start no earlier than three calendar months before its end (day
    clamped). Three calendar months span 89 to 92 days, so a ``90d`` window exceeds the
    limit on a few dates (for example 2025-01-31 to 2025-05-01); see cap_to_three_months.

    Args:
        window (DateWindow): Search window.

    Returns:
        bool: True when a search without ``corp_code`` accepts the window.
    """
    return window.start >= add_months(window.end, -3)


def cap_to_three_months(window: DateWindow) -> DateWindow:
    """Shorten a window to OpenDART's three-month limit for searches without a company.

    Args:
        window (DateWindow): Search window.

    Returns:
        DateWindow: The window itself when it fits, otherwise the same end with the start
            moved to three calendar months before it.
    """
    earliest = add_months(window.end, -3)
    return window if window.start >= earliest else DateWindow(earliest, window.end)


def yyyymmdd(value: date) -> str:
    """Format a date as OpenDART's ``YYYYMMDD``.

    Args:
        value (date): Date to format.

    Returns:
        str: Eight digits.
    """
    return f"{value.year:04d}{value.month:02d}{value.day:02d}"
