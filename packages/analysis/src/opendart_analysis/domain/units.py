"""Monetary display units.

``scale_amount`` converts exact won to million or billion won, rounded to one decimal
place, or keeps exact won. The unit statements that filing tables state in Korean, such as
``(단위 : 백만원)``, are read by ``opendart_analysis.documents.units``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opendart_analysis.domain.types import Unit

_DIVISORS: dict[Unit, int] = {"krw": 1, "million_krw": 10**6, "billion_krw": 10**9}
_LABELS: dict[Unit, str] = {
    "krw": "KRW",
    "million_krw": "KRW million",
    "billion_krw": "KRW billion",
}
_ONE_DECIMAL = Decimal("0.1")


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
