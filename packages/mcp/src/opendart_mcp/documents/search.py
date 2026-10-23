"""Search rendered filing text.

Body text is Korean, so Korean terms find prose; English terms find the English headings and
labels the filing supplies. Korean spacing varies, so a space may appear or vanish between any
two Hangul syllables of a term (``전환사채`` and ``전환 사채`` find each other), and whitespace
between terms matches any spacing. When a multi-word query has no exact match, its individual
words are searched instead and a note says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opendart_mcp.documents.tree import collapse

_BEFORE = 120
_AFTER = 180
_MIN_WORD = 2
_STOPWORDS = frozenset({"a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "by", "with"})
_HANGUL = re.compile(r"[가-힣]")
MAX_QUERY_CHARS = 1000


@dataclass(frozen=True, slots=True)
class Match:
    """A search match with its context.

    Attributes:
        offset (int): Start of the snippet within the searched text.
        position (int): Start of the match within the searched text.
        snippet (str): About 300 characters around the match, whitespace collapsed.
    """

    offset: int
    position: int
    snippet: str


@dataclass(frozen=True, slots=True)
class Found:
    """Search results within one text.

    Attributes:
        matches (list[Match]): Non-overlapping snippets, up to the limit, in order.
        total (int): Number of matches.
        exact (bool): False when individual words were searched instead of the phrase.
        limited (bool): True when the limit left matches without a snippet.
    """

    matches: list[Match]
    total: int
    exact: bool
    limited: bool


def search_text(text: str, query: str, limit: int) -> Found:
    """Find a query in text and cut snippets around matches.

    Args:
        text (str): Text to search.
        query (str): Search terms.
        limit (int): Most snippets to return.

    Returns:
        Found: Snippets, the total number of matches, and whether the phrase matched.

    Raises:
        ValueError: The query has no search terms or is longer than 1,000 characters.
    """
    terms = query.split()
    if not terms or len(query) > MAX_QUERY_CHARS:
        msg = f"query must contain search terms and at most {MAX_QUERY_CHARS:,} characters"
        raise ValueError(msg)
    phrase = re.compile(r"\s*".join(_term(term) for term in terms), re.IGNORECASE)
    positions = [match.start() for match in phrase.finditer(text)]
    if positions or len(terms) == 1:
        matches, limited = _snippets(text, positions, limit)
        return Found(matches, len(positions), exact=True, limited=limited)
    words = [t for t in terms if len(t) >= _MIN_WORD and t.lower() not in _STOPWORDS]
    alternatives = sorted(words or terms, key=len, reverse=True)
    pattern = re.compile("|".join(_term(word) for word in alternatives), re.IGNORECASE)
    positions = [match.start() for match in pattern.finditer(text)]
    matches, limited = _snippets(text, positions, limit)
    return Found(matches, len(positions), exact=False, limited=limited)


def _term(term: str) -> str:
    """Build the pattern for one search term.

    Args:
        term (str): A whitespace-free term.

    Returns:
        str: Escaped pattern; Hangul syllables may be separated by one whitespace character.
    """
    if not _HANGUL.search(term):
        return re.escape(term)
    return r"\s?".join(re.escape(character) for character in term)


def _snippets(text: str, positions: list[int], limit: int) -> tuple[list[Match], bool]:
    """Cut non-overlapping snippets around match positions.

    Args:
        text (str): Searched text.
        positions (list[int]): Match starts, ascending.
        limit (int): Most snippets to return.

    Returns:
        tuple[list[Match], bool]: Snippets that start at the match's line when it is close
            (matches inside an earlier snippet are not repeated), and whether the limit left
            matches without a snippet.
    """
    matches: list[Match] = []
    covered = -1
    for position in positions:
        if position < covered:
            continue
        if len(matches) >= limit:
            return matches, True
        line = text.rfind("\n", 0, position) + 1
        start, end = max(position - _BEFORE, line), min(position + _AFTER, len(text))
        covered = end
        prefix, suffix = ("…" if start > line else ""), ("…" if end < len(text) else "")
        matches.append(Match(start, position, f"{prefix}{collapse(text[start:end])}{suffix}"))
    return matches, False
