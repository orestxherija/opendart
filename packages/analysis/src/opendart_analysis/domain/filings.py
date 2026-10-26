"""Filing titles and the remark letters on filing-search results.

Titles from the English API may start with bracketed markers that say how the filing
relates to an earlier one, such as ``[Revision of statements]``; Korean titles use the
Korean equivalents such as ``[기재정정]``. KRX titles carry runs of padding spaces and
sometimes a Korean suffix, which is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from opendart_analysis.domain.names import has_hangul

if TYPE_CHECKING:
    from collections.abc import Mapping

    from opendart_analysis.domain.types import Market

TITLE_MARKERS: Mapping[str, str] = MappingProxyType(
    {
        "revision of statements": "Revision of statements",
        "corrected attachment": "Corrected attachment",
        "added attachment": "Added attachment",
        "modified registration": "Modified registration",
        "decision to extend": "Decision to extend",
        "conditions for issuance finalized": "Conditions for issuance finalized",
        "correction order imposed": "Correction order imposed",
        "requested submission of correction": "Requested submission of correction",
        "corrected description": "Corrected description",
        "기재정정": "Revision of statements",
        "첨부정정": "Corrected attachment",
        "첨부추가": "Added attachment",
        "변경등록": "Modified registration",
        "연장결정": "Decision to extend",
        "발행조건확정": "Conditions for issuance finalized",
        "정정명령부과": "Correction order imposed",
        "정정제출요구": "Requested submission of correction",
    }
)
"""Documented title markers (English and Korean, case-folded) to their English names."""

RESUBMISSION_MARKERS = frozenset(
    {
        "Revision of statements",
        "Corrected attachment",
        "Added attachment",
        "Modified registration",
        "Decision to extend",
        "Conditions for issuance finalized",
        "Corrected description",
    }
)
"""Markers meaning the filing re-submits an earlier one; the other two mark FSS orders.

"Corrected description" is how KRX exchange disclosures mark a correction."""

_LEADING_MARKER = re.compile(r"\s*\[([^\]]*)\]")
_CORRECTION_WORDS = re.compile(r"correct|revis|amend|modif|정정", re.IGNORECASE)
_REMARK_ALIASES = {
    "유": "S",
    "코": "K",
    "채": "B",
    "넥": "N",
    "공": "F",
    "연": "C",
    "정": "U",
    "철": "W",
}
_MARKET_LETTERS: tuple[tuple[str, Market], ...] = (("S", "KOSPI"), ("K", "KOSDAQ"), ("N", "KONEX"))


@dataclass(frozen=True, slots=True)
class RemarkFlags:
    """Meaning of the ``rm`` letters on a filing-search result.

    Attributes:
        market (Market | None): KRX division in charge: S (KOSPI), K (KOSDAQ), N (KONEX).
        bond_listed (bool): B, a disclosure of a company with listed bonds.
        fair_trade (bool): F, a Fair Trade Commission disclosure.
        consolidated (bool): C, the report includes consolidated portions.
        corrected_later (bool): U, a correction was filed after this report.
        withdrawn (bool): W, the report was withdrawn or deemed withdrawn.
    """

    market: Market | None
    bond_listed: bool
    fair_trade: bool
    consolidated: bool
    corrected_later: bool
    withdrawn: bool


def clean_title(title: str) -> str:
    """Collapse whitespace runs in a filing title, keeping any Korean suffix.

    Args:
        title (str): Raw title.

    Returns:
        str: Title with single spaces and no surrounding whitespace.
    """
    return " ".join(title.split())


def amendment_marker(title: str) -> str | None:
    """Return the leading bracketed marker of a filing title.

    Documented markers come back as their English names (``[기재정정]`` gives
    ``Revision of statements``). Other leading brackets are returned as written when they
    mention a correction, revision, amendment, or modification, and ignored otherwise.

    Args:
        title (str): Raw or cleaned title.

    Returns:
        str | None: Marker text, or None when the title has no amendment marker.
    """
    match = _LEADING_MARKER.match(title)
    if match is None:
        return None
    text = clean_title(match.group(1))
    known = TITLE_MARKERS.get(
        text.casefold().replace(" ", "") if has_hangul(text) else text.casefold()
    )
    if known is not None:
        return known
    return text if _CORRECTION_WORDS.search(text) else None


def is_amendment(title: str) -> bool:
    """Check whether a title marks a re-submission of an earlier filing.

    Args:
        title (str): Raw or cleaned title.

    Returns:
        bool: True for re-submission markers and other correction markers; False for FSS
            correction orders and requests, and for unmarked titles.
    """
    marker = amendment_marker(title)
    if marker is None:
        return False
    return marker in RESUBMISSION_MARKERS or marker not in TITLE_MARKERS.values()


def parse_remarks(rm: str | None) -> RemarkFlags:
    """Decode the ``rm`` letters of a filing-search result.

    English results use S, K, B, N, F, C, U, and W; the Korean letters 유, 코, 채, 넥, 공,
    연, 정, and 철 are accepted too. Unknown letters are ignored.

    Args:
        rm (str | None): Remark letters, such as ``"SC"``.

    Returns:
        RemarkFlags: Decoded flags; all false and no market for None or blank.
    """
    letters = {_REMARK_ALIASES.get(char, char) for char in (rm or "").upper()}
    market = next((name for letter, name in _MARKET_LETTERS if letter in letters), None)
    return RemarkFlags(
        market=market,
        bond_listed="B" in letters,
        fair_trade="F" in letters,
        consolidated="C" in letters,
        corrected_later="U" in letters,
        withdrawn="W" in letters,
    )
