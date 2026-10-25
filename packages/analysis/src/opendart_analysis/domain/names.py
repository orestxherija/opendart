"""Company-name normalization shared by the directory index and the resolver.

DART names are inconsistent: English names mix case and legal-form spellings such as
``CO,.LTD``, ``Co., Ltd.``, and ``Corporation``, and Korean names sometimes carry ``주식회사``
or ``(주)``. Normalization makes both forms of the same company compare equal while keeping
meaningful words such as "Holdings" or "Securities". ``split_names`` splits comma-separated
company lists without breaking names that contain commas.
"""

from __future__ import annotations

import re
import unicodedata

# Korean legal forms are removed wherever they appear; NFKC has already turned ㈜ into (주).
_KOREAN_FORMS = re.compile(r"주식회사|유한책임회사|유한회사|\(\s*[주유]\s*\)")
# Everything except letters, digits, and "&" separates words. Underscores and the Korean
# middle dot (NFKC maps ㆍ to the letter ᆞ) are word characters to the regex, so list them.
_SEPARATORS = re.compile(r"[^\w&]+|[_\u119e\u318d]+")
# Trailing English legal forms, matched word by word so "co., ltd." and "co,.ltd" both go.
_LEGAL_SUFFIXES = frozenset(
    {
        "&",
        "co",
        "coltd",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "limited",
        "llc",
        "ltd",
        "plc",
    }
)
# Separators between the entries of a company list, captured so that rejoining keeps them.
_LIST_SEPARATORS = re.compile(r"([,;\n])")
# An entry made only of legal forms and punctuation, left by splitting names such as
# "CO,.LTD", "Co., Ltd.", "Corp,.", or ", INCORPORATED".
_LEGAL_FRAGMENT = re.compile(
    r"[\s.()]*(?:(?:co|ltd|inc|corp|limited|plc|llc|coltd|company|corporation|incorporated"
    + r"|incorporation)\b[\s.()]*)*",
    re.IGNORECASE,
)


def normalize_name(text: str) -> str:
    """Normalize a company name for matching.

    Applies NFKC and case folding, removes Korean legal forms (``주식회사``, ``(주)``, ``㈜``,
    ``유한회사``, ``유한책임회사``, ``(유)``) anywhere, turns punctuation other than ``&`` into
    spaces, drops trailing English legal forms (``co``, ``ltd``, ``corp``, ``corporation``,
    ``inc``, ``limited``, ``plc``, ``company``, ``llc``), and collapses whitespace. At least
    one word is always kept, so a name made only of legal forms still normalizes to text.

    Args:
        text (str): Company name in English or Korean, or a user query.

    Returns:
        str: Lowercase words separated by single spaces; empty when no word remains.

    Examples:
        >>> normalize_name("SAMSUNG ELECTRONICS CO,.LTD")
        'samsung electronics'
        >>> normalize_name("(주)카카오")
        '카카오'
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    stripped = _KOREAN_FORMS.sub(" ", folded)
    words = _SEPARATORS.sub(" ", stripped if stripped.strip() else folded).split()
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def compact_name(text: str) -> str:
    """Normalize a company name and remove the spaces between its words.

    Korean names are usually written without spaces, and English names are spaced
    inconsistently ("Kakao Bank" versus "KakaoBank"), so the index compares compact forms.

    Args:
        text (str): Company name in English or Korean, or a user query.

    Returns:
        str: Normalized name without spaces.
    """
    return normalize_name(text).replace(" ", "")


def name_tokens(text: str) -> tuple[str, ...]:
    """Split a normalized company name into words.

    Args:
        text (str): Company name in English or Korean, or a user query.

    Returns:
        tuple[str, ...]: Normalized words in their original order.
    """
    return tuple(normalize_name(text).split())


def split_names(text: str) -> list[str]:
    """Split a list of company names or codes at commas, semicolons, and line breaks.

    Official names such as ``SAMSUNG ELECTRONICS CO,.LTD`` contain commas, so an entry made
    only of legal forms and punctuation (``.LTD``, `` Ltd.``, ``.``) is joined back to the
    entry before it, separator included.

    Args:
        text (str): Company names, stock codes, or corp codes.

    Returns:
        list[str]: Non-blank entries in order, without surrounding whitespace.

    Examples:
        >>> split_names("SAMSUNG ELECTRONICS CO,.LTD, SK hynix Inc.; 035420")
        ['SAMSUNG ELECTRONICS CO,.LTD', 'SK hynix Inc.', '035420']
    """
    parts = _LIST_SEPARATORS.split(text)
    names: list[str] = []
    for separator, part in zip(["", *parts[1::2]], parts[::2], strict=True):
        if not part.strip():
            continue
        if names and _LEGAL_FRAGMENT.fullmatch(part):
            names[-1] += separator + part.rstrip()
        else:
            names.append(part.strip())
    return names


def is_hangul(char: str) -> bool:
    """Check whether a character is a precomposed Hangul syllable.

    Args:
        char (str): One character.

    Returns:
        bool: True for U+AC00 through U+D7A3.
    """
    return "\uac00" <= char <= "\ud7a3"


def has_hangul(text: str) -> bool:
    """Check whether text contains a precomposed Hangul syllable.

    Args:
        text (str): Text to inspect.

    Returns:
        bool: True when any character is Hangul.
    """
    return any(is_hangul(char) for char in text)
