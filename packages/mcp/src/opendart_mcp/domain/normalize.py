"""Turn OpenDART's string fields into numbers, dates, and clean text.

Every field arrives as a string: amounts with thousands separators, blanks, ``-`` for
"none", parentheses or a leading ``△`` or ``-`` for negatives, and dates in several
layouts. These parsers never raise on junk; they return None instead, so a malformed cell
becomes a missing value rather than a failed tool call.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opendart_mcp.domain.types import Market

_MAX_NUMBER_CHARS = 64
_MINUS_SIGNS = frozenset({"-", "\u2212", "\u25b3"})  # Hyphen-minus, minus sign, white triangle.
_NUMBER = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+")
_COMPACT_DATE = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})")
_SEPARATED_DATE = re.compile(r"([0-9]{4})[-./년]([0-9]{1,2})[-./월]([0-9]{1,2})[.일]?")
_TEXT_PLACEHOLDERS = frozenset({"", "-", "\u2212", "\u2013", "\u2014", "\uff0d"})  # Dashes.
_MARKETS: dict[str, Market] = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "OTHER"}


def parse_decimal(text: str | None) -> Decimal | None:
    """Parse a number such as ``1,234.5``, ``(1,234)``, ``△1,234``, or ``-0.5``.

    Thousands separators must group by three. Parentheses and a leading ``-``, minus sign
    (U+2212), or ``△`` mean negative; a leading ``+`` is allowed. Full-width digits are accepted.

    Args:
        text (str | None): Raw field.

    Returns:
        Decimal | None: The number, or None for blanks, ``-``, and anything that is not a number.
    """
    if text is None:
        return None
    value = unicodedata.normalize("NFKC", text).strip()
    negative, digits = _split_sign(value)
    if len(value) > _MAX_NUMBER_CHARS or not _NUMBER.fullmatch(digits):
        return None
    # The pattern admits only plain decimal literals, which Decimal always accepts.
    number = Decimal(digits.replace(",", ""))
    return -number if negative else number


def parse_amount(text: str | None) -> int | None:
    """Parse a whole-number amount such as ``1,234,567`` or ``(1,234)``.

    Args:
        text (str | None): Raw field.

    Returns:
        int | None: The amount, or None for blanks, ``-``, fractions, and junk.
    """
    number = parse_decimal(text)
    if number is None or number != number.to_integral_value():
        return None
    return int(number)


def parse_percent(text: str | None) -> float | None:
    """Parse a percentage such as ``12.5``, ``12.5%``, ``-3.2 %``, or ``△3.2%p``.

    Args:
        text (str | None): Raw field.

    Returns:
        float | None: The value in percent units (12.5 for 12.5%), or None for junk.
    """
    if text is None:
        return None
    value = unicodedata.normalize("NFKC", text).strip().removesuffix("%p").removesuffix("%")
    number = parse_decimal(value)
    return None if number is None else float(number)


def parse_date(text: str | None) -> date | None:
    """Parse ``YYYYMMDD``, ``YYYY.MM.DD``, ``YYYY-MM-DD``, ``YYYY/MM/DD``, or ``YYYY년 MM월 DD일``.

    Spaces anywhere and a trailing period (``2025. 1. 5.``) are tolerated.

    Args:
        text (str | None): Raw field.

    Returns:
        date | None: The date, or None for blanks, ``-``, impossible dates, and junk.
    """
    if text is None:
        return None
    compact = "".join(unicodedata.normalize("NFKC", text).split())
    match = _COMPACT_DATE.fullmatch(compact) or _SEPARATED_DATE.fullmatch(compact)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def clean_text(text: str | None) -> str | None:
    """Collapse whitespace and map placeholders to None.

    Args:
        text (str | None): Raw field.

    Returns:
        str | None: Text with single spaces, or None for blanks and dash placeholders.
    """
    if text is None:
        return None
    collapsed = " ".join(text.split())
    return None if collapsed in _TEXT_PLACEHOLDERS else collapsed


def market_from_corp_cls(code: str | None) -> Market | None:
    """Map OpenDART's ``corp_cls`` to a market name.

    Args:
        code (str | None): ``Y`` (KOSPI), ``K`` (KOSDAQ), ``N`` (KONEX), or ``E`` (other).

    Returns:
        Market | None: Market name, or None for a missing or unknown code.
    """
    if code is None:
        return None
    return _MARKETS.get(code.strip().upper())


def _split_sign(value: str) -> tuple[bool, str]:
    """Separate a sign or accounting parentheses from the digits.

    Args:
        value (str): Stripped field.

    Returns:
        tuple[bool, str]: Whether the value is negative, and the remaining text.
    """
    if len(value) > 1 and value[0] == "(" and value[-1] == ")":
        return True, value[1:-1].strip()
    if value[:1] in _MINUS_SIGNS:
        return True, value[1:].strip()
    if value[:1] == "+":
        return False, value[1:].strip()
    return False, value
