"""Resolve a free-text company reference to one directory record, or explain why not.

A company reference is a name, stock code, or corp code. ``resolve`` turns that text into
a record only when one company clearly dominates; otherwise it returns ranked candidates
and a reason, so callers can tell an ambiguous reference from a missing one.

Selection rules, applied in order:

1. Code: a corp code or stock code (any form ``parse_identifier`` accepts) selects that
   company. A code-shaped input that is not in the directory is ``not_found``; it is never
   matched against names. A filing number is ``not_found``.
2. Exact name (the compact normalized query equals a Korean or English name):

   a. One listed company has the name: it is selected, unless the name matched only in
      English and at least three other listed companies have every query word as a whole
      word of their English name. That query is a business-group name ("Hyundai" equals
      HYUNDAI CORPORATION's English name but also starts Hyundai Motor, Hyundai Mobis, and
      others), so it is ambiguous.
   b. Several listed companies have the name (a delisted predecessor keeps its stock code,
      as with the two 삼성물산 records): the most recently modified one is selected when it
      is at least two years newer than each of the others; otherwise ambiguous.
   c. Only unlisted companies have the name: a single one is selected unless a listed
      company matches by prefix or word, in which case the reference is ambiguous
      ("Samsung" equals one unlisted company's English name).

3. Partial name (prefix and word matches together): selected when exactly one listed
   company matches (or, with no listed match, exactly one company), every query word is a
   whole word of its English or Korean name, and at most ten companies match by prefix or
   word in total. "LG Energy" selects LG Energy Solution; "Samsung Bio" and "현대차" stay
   ambiguous because "Bio" and "현대차" are not whole words of the names they prefix.
4. Fuzzy (only when nothing matches exactly, by prefix, or by word): the best match is
   selected when its similarity is at least 0.8 and at least 0.05 above every rival. When
   the best match is listed, only listed companies are rivals.

Ambiguous results list listed companies first, keeping the search order within each group.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from opendart_analysis.domain.dates import add_months
from opendart_analysis.domain.identifiers import parse_identifier
from opendart_analysis.domain.names import compact_name, name_tokens

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.domain.directory import Directory, Match
    from opendart_analysis.domain.records import CorpRecord

ResolutionReason = Literal["code", "exact", "dominant", "ambiguous", "not_found"]
"""Why a resolution selected a company, or why it did not."""

CANDIDATE_POOL = 25
"""Number of ranked search matches considered."""

_GROUP_MIN_LISTED = 3
_PARTIAL_MAX_MATCHES = 10
_FUZZY_ACCEPT = 0.8
_FUZZY_MARGIN = 0.05
_RECENCY_MONTHS = 24


@dataclass(frozen=True, slots=True)
class Resolution:
    """Outcome of resolving a company reference.

    Attributes:
        record (CorpRecord | None): Selected company, or None when ambiguous or not found.
        candidates (tuple[Match, ...]): Ranked matches considered; for ambiguous results,
            listed companies first.
        reason (ResolutionReason): ``code``, ``exact``, or ``dominant`` when a company was
            selected; otherwise ``ambiguous`` or ``not_found``.
    """

    record: CorpRecord | None
    candidates: tuple[Match, ...]
    reason: ResolutionReason


def resolve(directory: Directory, text: str) -> Resolution:
    """Resolve a company reference using the rules in the module docstring.

    Args:
        directory (Directory): Company directory.
        text (str): Company name, stock code, or corp code.

    Returns:
        Resolution: The selected company, or candidates with the reason none was selected.
    """
    matches = directory.search(text, limit=CANDIDATE_POOL)
    if not matches:
        return Resolution(None, (), "not_found")
    if parse_identifier(text) is not None:
        return Resolution(matches[0].record, matches, "code")
    exact = [match for match in matches if match.tier == "exact"]
    if exact:
        selected = _exact_choice(text, exact, matches)
        reason: ResolutionReason = "exact"
    else:
        selected = _partial_choice(text, matches) or _fuzzy_choice(matches)
        reason = "dominant"
    if selected is None:
        listed_first = sorted(matches, key=lambda match: not match.record.listed)
        return Resolution(None, tuple(listed_first), "ambiguous")
    return Resolution(selected, matches, reason)


def company_label(record: CorpRecord) -> str:
    """Describe a company for candidate lists.

    Args:
        record (CorpRecord): Company.

    Returns:
        str: For example ``SAMSUNG ELECTRONICS CO,.LTD (삼성전자; corp 00126380, stock
            005930, modified 2025-12-01)``.
    """
    korean = f"{record.name}; " if record.english_name else ""
    stock = f"stock {record.stock_code}" if record.stock_code else "unlisted"
    modified = f", modified {record.modified.isoformat()}" if record.modified else ""
    return f"{record.display_name} ({korean}corp {record.corp_code}, {stock}{modified})"


def _exact_choice(text: str, exact: list[Match], matches: Sequence[Match]) -> CorpRecord | None:
    """Apply the exact-name rules.

    Args:
        text (str): Query.
        exact (list[Match]): Exact matches, ranked (listed first, newest first).
        matches (Sequence[Match]): All ranked matches.

    Returns:
        CorpRecord | None: Selected company, or None when ambiguous.
    """
    listed = [match.record for match in exact if match.record.listed]
    if not listed:
        partial_listed = any(m.record.listed and m.tier in {"prefix", "token"} for m in matches)
        return exact[0].record if len(exact) == 1 and not partial_listed else None
    chosen = listed[0] if len(listed) == 1 else _clearly_newest(listed)
    if chosen is None or _is_group_name(text, chosen, matches):
        return None
    return chosen


def _clearly_newest(records: list[CorpRecord]) -> CorpRecord | None:
    """Pick the newest record when it is at least two years newer than every other one.

    Args:
        records (list[CorpRecord]): Records ranked newest first.

    Returns:
        CorpRecord | None: The newest record, or None when the dates do not settle it.
    """
    newest = records[0].modified
    for other in records[1:]:
        if newest is None or other.modified is None:
            return None
        if newest < add_months(other.modified, _RECENCY_MONTHS):
            return None
    return records[0]


def _is_group_name(text: str, chosen: CorpRecord, matches: Sequence[Match]) -> bool:
    """Check whether an English-only exact match is really a business-group name.

    Args:
        text (str): Query.
        chosen (CorpRecord): Listed company whose name equals the query.
        matches (Sequence[Match]): All ranked matches.

    Returns:
        bool: True when at least three other listed companies share all query words.
    """
    if compact_name(text) == compact_name(chosen.name):
        return False
    words = set(name_tokens(text))
    sharing = [
        match
        for match in matches
        if match.tier != "exact"
        and match.record.listed
        and words <= set(name_tokens(match.record.english_name or ""))
    ]
    return len(sharing) >= _GROUP_MIN_LISTED


def _partial_choice(text: str, matches: Sequence[Match]) -> CorpRecord | None:
    """Apply the partial-name rule to prefix and word matches.

    Args:
        text (str): Query.
        matches (Sequence[Match]): All ranked matches, none exact.

    Returns:
        CorpRecord | None: Selected company, or None.
    """
    partial = [match for match in matches if match.tier in {"prefix", "token"}]
    if not partial or len(partial) > _PARTIAL_MAX_MATCHES:
        return None
    listed = [match for match in partial if match.record.listed]
    pick = listed or partial
    if len(pick) != 1:
        return None
    record = pick[0].record
    words = set(name_tokens(text))
    names = (record.name, record.english_name or "")
    return record if any(words <= set(name_tokens(name)) for name in names) else None


def _fuzzy_choice(matches: Sequence[Match]) -> CorpRecord | None:
    """Apply the fuzzy rule when every match is fuzzy.

    Args:
        matches (Sequence[Match]): All ranked matches.

    Returns:
        CorpRecord | None: Selected company, or None.
    """
    if any(match.tier != "fuzzy" for match in matches):
        return None
    best = matches[0]
    rivals = [match for match in matches[1:] if match.record.listed or not best.record.listed]
    if best.score < _FUZZY_ACCEPT or any(
        best.score - rival.score < _FUZZY_MARGIN for rival in rivals
    ):
        return None
    return best.record
