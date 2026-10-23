"""Monetary display units and the Korean unit statements found in filings.

Tool results show amounts in million won by default, rounded to one decimal place, while
detailed results keep exact won. Filing tables state their own unit in Korean, such as
``(단위 : 백만원)``; the document parser reads it with ``parse_unit_statement``.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opendart_mcp.domain.types import Unit

_DIVISORS: dict[Unit, int] = {"krw": 1, "million_krw": 10**6, "billion_krw": 10**9}
_LABELS: dict[Unit, str] = {
    "krw": "KRW",
    "million_krw": "KRW million",
    "billion_krw": "KRW billion",
}
_ONE_DECIMAL = Decimal("0.1")
# Korean numeral prefixes before 원 (won): 천원 is thousands of won, 억원 hundreds of millions.
_KOREAN_SCALES = {
    "": 1,
    "천": 10**3,
    "만": 10**4,
    "십만": 10**5,
    "백만": 10**6,
    "천만": 10**7,
    "억": 10**8,
    "십억": 10**9,
    "백억": 10**10,
    "천억": 10**11,
    "조": 10**12,
}
_UNIT_STATEMENT = re.compile(r"단\s*위\s*:?\s*([^)\]\u3011\n]*)")
_UNIT_SEPARATORS = re.compile(r"[,/\u00b7]")


def scale_amount(amount: int | None, unit: Unit) -> int | float | None:
    """Convert an amount in won to a display unit.

    Args:
        amount (int | None): Exact amount in won.
        unit (Unit): ``krw`` keeps the exact integer; ``million_krw`` and ``billion_krw``
            divide and round half up to one decimal place.

    Returns:
        int | float | None: Scaled amount, or None when amount is None.
    """
    if amount is None:
        return None
    if unit == "krw":
        return amount
    scaled = Decimal(amount) / _DIVISORS[unit]
    return float(scaled.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP))


def unit_label(unit: Unit) -> str:
    """Name a display unit.

    Args:
        unit (Unit): Display unit.

    Returns:
        str: ``KRW``, ``KRW million``, or ``KRW billion``.
    """
    return _LABELS[unit]


def korean_unit_multiplier(text: str) -> int | None:
    """Convert a Korean currency unit such as ``백만원`` to its multiplier in won.

    Supports 원, 천원, 만원, 십만원, 백만원, 천만원, 억원, 십억원, 백억원, 천억원, and 조원;
    spaces are ignored (``백만 원``).

    Args:
        text (str): Unit text.

    Returns:
        int | None: Won per unit, or None when the text is not a Korean won unit.
    """
    compact = "".join(unicodedata.normalize("NFKC", text).split())
    if not compact.endswith("원"):
        return None
    return _KOREAN_SCALES.get(compact.removesuffix("원"))


def parse_unit_statement(text: str) -> tuple[int | None, bool]:
    """Find a unit statement such as ``(단위 : 백만원)`` or ``구분(단위 : 조원, %)``.

    The statement lists units after ``단위`` (unit), up to a closing bracket or line end.
    The first Korean won unit sets the multiplier; ``%`` marks percentage columns. Other
    units such as ``주`` (shares) or foreign currencies are ignored.

    Args:
        text (str): Caption or cell text.

    Returns:
        tuple[int | None, bool]: Won multiplier (None when no won unit is stated) and
            whether percentages are stated.
    """
    match = _UNIT_STATEMENT.search(unicodedata.normalize("NFKC", text))
    if match is None:
        return None, False
    parts = [part.strip() for part in _UNIT_SEPARATORS.split(match.group(1))]
    multipliers = [korean_unit_multiplier(part) for part in parts if part and "%" not in part]
    multiplier = next((value for value in multipliers if value is not None), None)
    return multiplier, any("%" in part for part in parts)
