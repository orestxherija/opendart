"""Read periodic-report records safely: strings, amounts, labels, totals, and term labels.

Every field of a periodic-report record is a string: amounts with thousands separators, ``-``
for nothing, labels in English or Korean, total rows mixed with data rows, and term labels such
as ``제57기 (당기)`` (57th term, current) for tables that cover three fiscal years. Field and
container names are the SDK's, as ``opendart_analysis.catalog`` lists them (``FieldSpec.name``
and ``RecordSpec.path``), so SDK records are read as they are and never copied or mutated.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.normalize import clean_text, parse_amount

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_TOTAL_LABELS: Final = frozenset({"합계", "계", "총계", "소계", "total", "subtotal", "sum"})
# "Not applicable" placeholders that filers write instead of leaving a cell blank.
_NOT_APPLICABLE: Final = frozenset(
    {"해당사항없음", "해당사항없습니다", "해당없음", "없음", "n/a", "na", "none", "notapplicable"}
)
# Korean 기 (term) or an English ordinal suffix, as in 57th.
_TERM_NUMBER: Final = re.compile(r"(\d{1,4})\s*(?:기|th|st|[nr]d)(?![a-z])", re.IGNORECASE)
_YEAR: Final = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_TERM_WORDS: Final = (
    ("전전기", 2),
    ("전기", 1),
    ("당기", 0),
    ("twoyearsprior", 2),
    ("prior", 1),
    ("previous", 1),
    ("current", 0),
)


def records(response: object, name: str = "list") -> list[object]:
    """Read a record container from a response.

    Args:
        response (object): Service response, such as an SDK response model.
        name (str): Container attribute: ``list``, or ``group`` for the Ver 2.0 services.

    Returns:
        list[object]: Records, empty when the container is missing.
    """
    value = getattr(response, name, None)
    return list(value) if isinstance(value, list) else []


def text(record: object, name: str) -> str | None:
    """Read one string field from a record.

    Args:
        record (object): Record, such as an SDK record model.
        name (str): Field name, as the SDK and the catalog name it.

    Returns:
        str | None: The raw value, or None when the field is missing or not a string.
    """
    value = getattr(record, name, None)
    return value if isinstance(value, str) else None


def amount(record: object, name: str) -> int | None:
    """Read one whole-number amount field, such as ``1,234,567`` or ``(1,234)``.

    Args:
        record (object): Record, such as an SDK record model.
        name (str): Field name, as the SDK and the catalog name it.

    Returns:
        int | None: The amount, or None for a missing field, ``-``, fractions, and junk.
    """
    return parse_amount(text(record, name))


def fold(value: str | None) -> str:
    """Fold a label for matching: no whitespace, case-folded.

    Args:
        value (str | None): Label.

    Returns:
        str: Folded label; empty for None.
    """
    return "".join((value or "").split()).casefold()


def is_total(value: str | None) -> bool:
    """Tell whether a row label marks a total, such as 합계, 계, or Total.

    Args:
        value (str | None): Row label.

    Returns:
        bool: True for total and subtotal labels.
    """
    return fold(value) in _TOTAL_LABELS


def filed_text(value: str | None) -> str | None:
    """Clean free text and drop dashes and "not applicable" placeholders.

    Args:
        value (str | None): Raw field.

    Returns:
        str | None: Text with single spaces, or None.
    """
    cleaned = clean_text(value)
    if cleaned is None or fold(cleaned).rstrip(".") in _NOT_APPLICABLE:
        return None
    return cleaned


def sum_known(values: Iterable[int | None]) -> int | None:
    """Add the known values.

    Args:
        values (Iterable[int | None]): Values; None means unknown or not filed.

    Returns:
        int | None: The sum, or None when every value is unknown.
    """
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def term_ages(labels: Sequence[str | None]) -> list[int]:
    """Number each row's fiscal term back from the newest: 0 current, 1 prior, and so on.

    Rows carry labels such as ``제57기 (당기)`` or ``2025``. Years, or else term numbers,
    decide when every label has one (filers sometimes mislabel older terms as 당기,
    current); otherwise the words 당기, 전기, and 전전기 (current, prior, two years prior)
    decide, and failing both, the order in which labels first appear. Blank labels continue
    the previous row's term.

    Args:
        labels (Sequence[str | None]): Term label of each row, in row order.

    Returns:
        list[int]: Age of each row's term in fiscal years.
    """
    filled: list[str] = []
    for label in labels:
        filled.append(clean_text(label) or (filled[-1] if filled else ""))
    for pattern in (_YEAR, _TERM_NUMBER):
        numbers = [_number(pattern, label) for label in filled]
        known = [n for n in numbers if n is not None]
        if filled and len(known) == len(filled):
            return [max(known) - n for n in known]
    words = [_term_word(label) for label in filled]
    if all(word is not None for word in words):
        return [word or 0 for word in words]
    order = list(dict.fromkeys(filled))
    return [order.index(label) for label in filled]


def _number(pattern: re.Pattern[str], label: str) -> int | None:
    """Read a fiscal year or term number from a term label.

    Args:
        pattern (re.Pattern[str]): Pattern whose first group is the number.
        label (str): Term label.

    Returns:
        int | None: The number, or None when the label has none.
    """
    match = pattern.search(label)
    return int(match.group(1)) if match else None


def _term_word(label: str) -> int | None:
    """Read a term's age from words such as 전기 (prior term).

    Args:
        label (str): Term label.

    Returns:
        int | None: Age in fiscal years, or None when no word matches.
    """
    folded = fold(label)
    return next((age for word, age in _TERM_WORDS if word in folded), None)
