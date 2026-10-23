"""Unit statements in filing tables: detection, English rendering, and won multipliers.

Korean filings state units as text inside a table or next to it, for example
``(단위 : 백만원)``, ``단위 : 조원, %``, or ``구분(단위 : 백만원, %)``. Tables are never rescaled;
the statement is translated and shown above the table, and monetary multipliers support the
preliminary-earnings extractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Fullwidth forms are escaped: \uff08 \uff09 parentheses, \uff1a colon, \uff0c comma,
# \u3014 \u3015 tortoise-shell brackets. "단위" preceded by another syllable is part of a word,
# as in 현금창출단위 (cash-generating unit), so it does not start a unit statement.
_OPEN = "(\\[\uff08【\u3014<"
_CLOSE = ")\\]\uff09】\u3015>"
_UNIT_PATTERN = re.compile(
    rf"[{_OPEN}]?\s*(?<![가-힣])단\s*위\s*[:\uff1a]\s*(?P<body>[^{_CLOSE}\n]*?)\s*(?:[{_CLOSE}]|$)",
    re.MULTILINE,
)
_TOKEN_SPLIT = re.compile("\\s*[,\uff0c\u3001]\\s*")
_BRACKETS = "()[]\uff08\uff09【】\u3014\u3015<>"

_WON_MULTIPLIERS: dict[str, int] = {
    "원": 1,
    "천원": 10**3,
    "만원": 10**4,
    "백만원": 10**6,
    "천만원": 10**7,
    "억원": 10**8,
    "십억원": 10**9,
    "조원": 10**12,
}

_TOKENS: dict[str, str] = {
    "원": "KRW",
    "천원": "KRW thousand",
    "만원": "KRW 10 thousand",
    "백만원": "KRW million",
    "천만원": "KRW 10 million",
    "억원": "KRW 100 million",
    "십억원": "KRW billion",
    "조원": "KRW trillion",
    "원/주": "KRW per share",
    "주당원": "KRW per share",
    "%": "%",
    "\uff05": "%",
    "주": "shares",
    "천주": "thousand shares",
    "만주": "10 thousand shares",
    "백만주": "million shares",
    "명": "persons",
    "건": "cases",
    "개": "units",
    "대": "units",
    "개사": "companies",
    "사": "companies",
    "배": "times",
    "회": "times",
    "시간": "hours",
    "일": "days",
    "개월": "months",
    "년": "years",
    "매": "sheets",
    "톤": "tons",
    "㎡": "m²",
    "m2": "m²",
    "평": "pyeong",
    "달러": "USD",
    "US$": "USD",
    "천달러": "USD thousand",
    "천USD": "USD thousand",
    "USD천": "USD thousand",
    "백만달러": "USD million",
    "백만USD": "USD million",
    "USD백만": "USD million",
    "엔": "JPY",
    "위안": "CNY",
    "유로": "EUR",
}


@dataclass(frozen=True, slots=True)
class UnitStatement:
    """A unit statement found in text.

    Attributes:
        raw (str): The statement as written, for example ``(단위 : 백만원, %)``.
        body (str): The unit list after the colon, for example ``백만원, %``.
    """

    raw: str
    body: str

    @property
    def english(self) -> str:
        """Return the unit list in English, for example ``KRW million, %``.

        Returns:
            str: Translated unit list; unknown units are kept verbatim.
        """
        return translate_units(self.body)

    @property
    def multiplier(self) -> int | None:
        """Return the multiplier of the first won unit, for example 1,000,000 for 백만원.

        Returns:
            int | None: Won per stated unit, or None when no won unit is stated.
        """
        return won_multiplier(self.body)


def find_unit_statement(text: str) -> UnitStatement | None:
    """Find the first unit statement in text.

    Args:
        text (str): Cell, caption, or paragraph text.

    Returns:
        UnitStatement | None: The statement, or None when the text states no unit.
    """
    if "위" not in text:
        return None
    match = _UNIT_PATTERN.search(text)
    if match is None or not match.group("body").strip():
        return None
    return UnitStatement(raw=match.group(0).strip(), body=match.group("body").strip())


def is_unit_only(text: str) -> bool:
    """Report whether text consists of nothing but a unit statement.

    Args:
        text (str): Cell or paragraph text.

    Returns:
        bool: True for text such as ``(단위 : 원)`` or ``[단위: 백만원, %]``.
    """
    statement = find_unit_statement(text)
    if statement is None:
        return False
    rest = text.replace(statement.raw, "", 1)
    return not rest.strip().strip(_BRACKETS).strip()


def translate_units(body: str) -> str:
    """Translate a Korean unit list into English.

    Args:
        body (str): Unit list such as ``백만원, %`` or ``천원, USD``.

    Returns:
        str: English unit list such as ``KRW million, %``; unknown units stay verbatim.
    """
    tokens = [token for token in _TOKEN_SPLIT.split(body.strip()) if token]
    return ", ".join(_TOKENS.get(token.replace(" ", ""), token) for token in tokens)


def won_multiplier(text: str) -> int | None:
    """Return the multiplier of the first won unit in a unit list or statement.

    Args:
        text (str): Unit list (``억원, %``) or text containing a unit statement.

    Returns:
        int | None: Won per stated unit, or None when no won unit is found.
    """
    statement = find_unit_statement(text)
    body = statement.body if statement is not None else text
    for token in _TOKEN_SPLIT.split(body.strip()):
        multiplier = _WON_MULTIPLIERS.get(token.replace(" ", ""))
        if multiplier is not None:
            return multiplier
    return None


def won_unit(text: str) -> tuple[int, str] | None:
    """Return the multiplier and English name of the first won unit in a unit statement.

    Args:
        text (str): Unit list or text containing a unit statement, such as ``단위 : 억원, %``.

    Returns:
        tuple[int, str] | None: Multiplier and name, such as ``(100000000, "KRW 100 million")``,
            or None when no won unit is stated.
    """
    statement = find_unit_statement(text)
    body = statement.body if statement is not None else text
    for token in _TOKEN_SPLIT.split(body.strip()):
        key = token.replace(" ", "")
        if key in _WON_MULTIPLIERS:
            return _WON_MULTIPLIERS[key], _TOKENS[key]
    return None
