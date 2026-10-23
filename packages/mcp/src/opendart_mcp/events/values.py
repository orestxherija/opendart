"""Normalize event report values by field kind, and format them for headlines.

Event reports send every value as text: amounts with separators, dashes for "none", English
or Korean yes/no words ("Non-applicable", "N/A", "해당사항 없음"), and dates that are sometimes
ranges such as ``2026.12.14 ~ 2026.12.15``. The registry's FieldKind says how to read each
field. These helpers never raise on malformed text; they return None, or the cleaned text
when a date field holds words.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.normalize import (
    clean_text,
    parse_amount,
    parse_date,
    parse_decimal,
    parse_percent,
)

if TYPE_CHECKING:
    from collections.abc import Callable

type Scalar = str | int | float | bool | None
"""A normalized value: integer won and counts, floats, ISO dates, flags, or text."""

TEXT_LIMIT: Final = 160
"""Longest text kept in concise key terms."""
HEADLINE_TEXT_LIMIT: Final = 60
"""Longest text fragment shown in a headline."""

_TRUE: Final = frozenset(
    {"y", "yes", "applicable", "present", "true", "o", "해당", "예", "있음", "유", "참석"}
)
_FALSE: Final = frozenset(
    {
        "n",
        "no",
        "non-applicable",
        "notapplicable",
        "n/a",
        "na",
        "absent",
        "false",
        "x",
        "해당없음",
        "해당사항없음",
        "미해당",
        "아니오",
        "없음",
        "무",
        "불참",
    }
)
# Tilde, tilde operator, full-width tilde, and wave dash separate the ends of a range.
_RANGE_SEPARATOR: Final = re.compile("\\s*[~\u223c\uff5e\u301c]\\s*")
_MONTH_DAY: Final = re.compile(r"([0-9]{1,2})[./-]([0-9]{1,2})\.?")
_UNIT_SUFFIXES: Final = ("shares", "shrs.", "shrs", "krw", "won", "주", "원")
_WON_SCALES: Final = ((1e12, "tn"), (1e9, "bn"), (1e6, "m"))


def parse_flag(raw: str | None) -> bool | None:
    """Read a yes/no value written in English or Korean.

    Args:
        raw (str | None): Raw field, such as "Y", "Non-applicable", "Absent", or "해당".

    Returns:
        bool | None: True or False, or None for blanks and other text.
    """
    text = clean_text(raw)
    if text is None:
        return None
    key = text.casefold().replace(" ", "")
    if key in _TRUE:
        return True
    return False if key in _FALSE else None


def parse_span(raw: str | None) -> tuple[date, date] | None:
    """Read a date or a date range such as ``2026.12.14 ~ 2026.12.15``.

    The end of a range may omit the year (``2026.12.14 ~ 12.15``); a year-less end before
    the start falls in the next year (``2026.12.28 ~ 01.08`` ends on 2027-01-08).

    Args:
        raw (str | None): Raw field.

    Returns:
        tuple[date, date] | None: First and last day (equal for a single date), or None
            when the text is not a date or the range runs backwards.
    """
    text = clean_text(raw)
    if text is None:
        return None
    start_text, *ends = _RANGE_SEPARATOR.split(text)
    if not ends:
        day = parse_date(text)
        return (day, day) if day else None
    start = parse_date(start_text) if len(ends) == 1 else None
    end = _range_end(ends[-1], start)
    return (start, end) if start and end and start <= end else None


def _range_end(text: str, start: date | None) -> date | None:
    """Read the end of a range, borrowing the start's year when it is missing.

    Args:
        text (str): End text, such as ``2026.12.15`` or ``12.15``.
        start (date | None): Start of the range.

    Returns:
        date | None: End date, or None when unreadable. A year-less month and day before
            the start's fall in the following year.
    """
    full = parse_date(text)
    if full is not None or start is None:
        return full
    match = _MONTH_DAY.fullmatch(text.strip())
    if match is None:
        return None
    month, day = int(match[1]), int(match[2])
    year = start.year if (month, day) >= (start.month, start.day) else start.year + 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _strip_units(raw: str | None) -> str | None:
    """Drop a trailing unit word such as "주" or "KRW" from a number.

    Args:
        raw (str | None): Raw field.

    Returns:
        str | None: Cleaned text without the unit, or None for blanks.
    """
    text = clean_text(raw)
    if text is None:
        return None
    lowered = text.casefold()
    suffix = next((s for s in _UNIT_SUFFIXES if lowered.endswith(s)), "")
    return text[: len(text) - len(suffix)].strip()


def _amount(raw: str | None) -> int | None:
    """Parse a whole amount or count, ignoring a unit word.

    Args:
        raw (str | None): Raw field.

    Returns:
        int | None: The number, or None.
    """
    return parse_amount(_strip_units(raw))


def _number(raw: str | None) -> int | float | None:
    """Parse a price or other number, keeping integers as int.

    Args:
        raw (str | None): Raw field.

    Returns:
        int | float | None: The number, or None.
    """
    value = parse_decimal(_strip_units(raw))
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _when(raw: str | None) -> str | None:
    """Normalize a date or range to ISO, keeping words such as "미정" as text.

    Args:
        raw (str | None): Raw field.

    Returns:
        str | None: ``YYYY-MM-DD``, ``YYYY-MM-DD/YYYY-MM-DD``, cleaned text, or None.
    """
    span = parse_span(raw)
    if span is None:
        return clean_text(raw)
    start, end = span
    return start.isoformat() if start == end else f"{start.isoformat()}/{end.isoformat()}"


_PARSERS: Final[dict[str, Callable[[str | None], Scalar]]] = {
    "amount": _amount,
    "count": _amount,
    "per_share": _number,
    "number": _number,
    "percent": parse_percent,
    "flag": parse_flag,
    "date": _when,
    "period": _when,
}


def normalize(kind: str, raw: str | None) -> Scalar:
    """Normalize one raw value by its registry field kind.

    Args:
        kind (str): Registry FieldKind, such as amount, percent, or date.
        raw (str | None): Raw field.

    Returns:
        Scalar: Integer won and counts, floats for percents, ISO dates, flags, or cleaned
            text for codes, ratios, and free text.
    """
    return _PARSERS.get(kind, clean_text)(raw)


def won(value: float) -> str:
    """Format a won amount compactly.

    Args:
        value (float): Amount in won.

    Returns:
        str: For example "KRW 5.0bn", "KRW 1.2tn", "KRW 350m", or "KRW 52,000".
    """
    size = abs(value)
    for threshold, suffix in _WON_SCALES:
        if size >= threshold:
            return f"KRW {value / threshold:,.1f}{suffix}"
    return f"KRW {value:,.0f}"


def shorten(text: str, limit: int) -> str:
    """Cut text to a length, marking the cut.

    Args:
        text (str): Text to cut.
        limit (int): Maximum characters, including the marker.

    Returns:
        str: The text, or its start followed by "...".
    """
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


_NUMBER_DISPLAY: Final[dict[str, Callable[[float], str]]] = {
    "amount": won,
    "per_share": lambda value: f"KRW {value:,}",
    "count": lambda value: f"{value:,}",
    "number": lambda value: f"{value:,}",
    "percent": lambda value: f"{value:g}%",
}


def display(kind: str, value: Scalar) -> str | None:
    """Format a normalized value for a headline.

    Args:
        kind (str): Registry FieldKind of the value.
        value (Scalar): Normalized value.

    Returns:
        str | None: Display text, or None when there is no value to show.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    formatter = _NUMBER_DISPLAY.get(kind)
    if formatter is not None and isinstance(value, int | float):
        return formatter(value)
    text = str(value).replace("/", " to ") if kind in {"date", "period"} else str(value)
    return shorten(text, HEADLINE_TEXT_LIMIT)
