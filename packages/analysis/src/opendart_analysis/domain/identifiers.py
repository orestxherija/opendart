"""Recognize DART corp codes, KRX stock codes, and filing numbers in free text.

Corp codes have 8 digits. Stock codes have 6 characters: digits, or since 2024 digits with a
letter in the fifth position (``0088M0``). Filing numbers have 14 digits: the filing date
(``YYYYMMDD``) followed by a 6-digit sequence whose first two digits name the source:
``00`` for FSS filings, ``80`` for KRX KOSPI disclosures, and ``90`` for KRX KOSDAQ ones.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

IdentifierKind = Literal["corp_code", "stock_code", "filing_number"]
"""Kind of identifier recognized by parse_identifier."""

FilingOrigin = Literal["fss", "krx_kospi", "krx_kosdaq", "krx_konex", "other"]
"""Origin of a filing, from the sequence part of its number."""

DART_VIEWER_URL = "https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo={filing_number}"
"""English DART viewer link template documented by OpenDART."""

_CORP_CODE = re.compile(r"[0-9]{8}")
_FILING_NUMBER = re.compile(r"[0-9]{14}")
_STOCK_CODE = re.compile(
    r"""
    (?:(?:KRX|KOSPI|KOSDAQ|KONEX)\s*[:-]\s*)?        # exchange prefix, such as KRX:005930
    A?([0-9]{4}[0-9A-Z][0-9])                       # Korean brokers' "A" prefix, then the code
    (?:\.(?:KS|KQ|KN)|\s+(?:KS|KQ)(?:\s+EQUITY)?)?   # Yahoo or Bloomberg suffix
    """,
    re.VERBOSE,
)
_ORIGINS: dict[str, FilingOrigin] = {
    "00": "fss",
    "60": "krx_konex",
    "80": "krx_kospi",
    "90": "krx_kosdaq",
}


@dataclass(frozen=True, slots=True)
class Identifier:
    """A recognized identifier in canonical form.

    Attributes:
        kind (IdentifierKind): What the value identifies.
        value (str): Canonical value: 8 digits, 6 uppercase characters, or 14 digits.
    """

    kind: IdentifierKind
    value: str


def parse_identifier(text: str) -> Identifier | None:
    """Recognize a corp code, stock code, or filing number.

    Accepted forms: ``00126380`` (corp code); ``005930``, ``A005930``, ``005930.KS``,
    ``005930.KQ``, ``005930 KS``, ``KRX:005930``, ``KOSPI:005930``, and alphanumeric codes
    such as ``0088M0`` in any case (stock code); 14 digits (filing number). Surrounding
    whitespace and full-width characters are tolerated.

    Args:
        text (str): User input.

    Returns:
        Identifier | None: The identifier, or None when the text is not code-shaped.
    """
    candidate = unicodedata.normalize("NFKC", text).strip().upper()
    if _CORP_CODE.fullmatch(candidate):
        return Identifier("corp_code", candidate)
    if _FILING_NUMBER.fullmatch(candidate):
        return Identifier("filing_number", candidate)
    match = _STOCK_CODE.fullmatch(candidate)
    if match:
        return Identifier("stock_code", match.group(1))
    return None


def is_corp_code(text: str) -> bool:
    """Check whether text is exactly an 8-digit corp code.

    Args:
        text (str): Candidate corp code.

    Returns:
        bool: True for exactly 8 ASCII digits.
    """
    return _CORP_CODE.fullmatch(text) is not None


def is_filing_number(text: str) -> bool:
    """Check whether text is exactly a 14-digit filing number.

    Args:
        text (str): Candidate filing number.

    Returns:
        bool: True for exactly 14 ASCII digits.
    """
    return _FILING_NUMBER.fullmatch(text) is not None


def dart_viewer_url(filing_number: str) -> str:
    """Build the English DART viewer link for a filing.

    Args:
        filing_number (str): 14-digit filing number; surrounding whitespace is ignored.

    Returns:
        str: Viewer URL.

    Raises:
        ValueError: The value is not a 14-digit filing number.
    """
    number = filing_number.strip()
    if not is_filing_number(number):
        msg = f"Expected a 14-digit filing number, got {filing_number!r}"
        raise ValueError(msg)
    return DART_VIEWER_URL.format(filing_number=number)


def filing_date(filing_number: str) -> date | None:
    """Derive the filing date from the first eight digits of a filing number.

    Args:
        filing_number (str): 14-digit filing number.

    Returns:
        date | None: Filing date, or None when the number or its date part is invalid.
    """
    number = filing_number.strip()
    if not is_filing_number(number):
        return None
    try:
        return date(int(number[:4]), int(number[4:6]), int(number[6:8]))
    except ValueError:
        return None


def filing_origin(filing_number: str) -> FilingOrigin:
    """Classify where a filing was submitted, from its sequence prefix.

    Args:
        filing_number (str): 14-digit filing number.

    Returns:
        FilingOrigin: ``fss`` (``00``), ``krx_konex`` (``60``), ``krx_kospi`` (``80``),
            ``krx_kosdaq`` (``90``), or ``other`` for any other prefix or an invalid number.
    """
    number = filing_number.strip()
    if not is_filing_number(number):
        return "other"
    return _ORIGINS.get(number[8:10], "other")
