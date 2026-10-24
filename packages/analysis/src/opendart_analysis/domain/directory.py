"""The company directory: records, lookups by code, and ranked name search.

``domain.corpcode.parse_directory`` streams OpenDART's corporation-code ZIP into ``CorpRecord``
values and ``Directory.build`` indexes them. The directory keeps its columns packed (about 20 MB for
the full 120,000-company file, versus 30 MB for the parsed records) and rebuilds
``CorpRecord`` values on demand, so callers can drop the parsed records after building.
"""

from __future__ import annotations

import bisect
import heapq
from array import array
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from opendart_analysis.domain.identifiers import is_corp_code, parse_identifier
from opendart_analysis.domain.name_index import NameIndex
from opendart_analysis.domain.names import has_hangul, normalize_name
from opendart_analysis.domain.packed import PackedStrings
from opendart_analysis.domain.records import CorpRecord

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import datetime

    from opendart_analysis.domain.identifiers import Identifier
    from opendart_analysis.domain.name_index import Hits

__all__ = [
    "TIER_ORDER",
    "CorpRecord",
    "Directory",
    "Match",
    "MatchTier",
]

MatchTier = Literal["code", "exact", "prefix", "token", "fuzzy"]
"""How a search result matched, from strongest to weakest."""

TIER_ORDER: tuple[MatchTier, ...] = ("code", "exact", "prefix", "token", "fuzzy")
"""Tiers from strongest to weakest; a tier's position is its rank."""

type _Hit = tuple[int, float, int]  # Tier rank, score, matched name length.
type _Rank = tuple[int, int, float, int, int, int]
type _Lookups = list[tuple[MatchTier, tuple[Callable[[], Hits], ...]]]

_MIN_PARTIAL_CHARS = 2  # Shorter queries only match names exactly.


@dataclass(frozen=True, slots=True)
class Match:
    """One ranked search result.

    Attributes:
        record (CorpRecord): Matched company.
        score (float): Strength within the tier, from 0 to 1: 1 for codes and exact names,
            the share of the matched name the query covers for prefix and word matches,
            and the difflib similarity ratio for fuzzy matches.
        tier (MatchTier): How the company matched.
    """

    record: CorpRecord
    score: float
    tier: MatchTier


class Directory:
    """Immutable index of the corporation-code directory.

    Name search runs these tiers in order and stops once enough companies are found:

    1. ``code``: the query is a corp or stock code (see ``parse_identifier``). Code-shaped
       queries never fall through to name matching.
    2. ``exact``: the compact normalized query equals a Korean or English name.
    3. ``prefix``: a compact name starts with the query (two or more characters).
    4. ``token``: every query word of two or more characters starts a word of a multi-word
       name, in any order; or, for queries containing Hangul, a compact Korean name
       contains the query ("하이닉스" finds "SK하이닉스").
    5. ``fuzzy``: difflib similarity of at least 0.75 against listed companies sharing
       character bigrams with the query, and against any company sorting near the query
       that shares its first three characters (two for Hangul).

    Results are ranked by tier, then listed before unlisted, then score (descending), then
    shorter matched name, then the more recently modified record, then corp code.
    """

    __slots__ = (
        "_by_stock",
        "_codes",
        "_english",
        "_index",
        "_loaded_at",
        "_modified",
        "_names",
        "_stock",
    )

    def __init__(self, records: Iterable[CorpRecord], *, loaded_at: datetime) -> None:
        """Index records; same as ``build``.

        Args:
            records (Iterable[CorpRecord]): Parsed records, usually from parse_directory.
            loaded_at (datetime): When the archive was downloaded.
        """
        ordered = _unique_by_code(records)
        self._loaded_at = loaded_at
        self._codes = array("I", (int(record.corp_code) for record in ordered))
        self._names = PackedStrings(record.name for record in ordered)
        self._english = PackedStrings(record.english_name or "" for record in ordered)
        self._modified = array("I", (_date_number(record.modified) for record in ordered))
        self._stock = {
            i: record.stock_code for i, record in enumerate(ordered) if record.stock_code
        }
        self._by_stock: dict[str, int] = {}
        for position, code in self._stock.items():
            other = self._by_stock.get(code)
            if other is None or self._modified[position] > self._modified[other]:
                self._by_stock[code] = position
        self._index = NameIndex.build(
            [record.name for record in ordered],
            [record.english_name for record in ordered],
            [record.listed for record in ordered],
        )

    @classmethod
    def build(cls, records: Iterable[CorpRecord], *, loaded_at: datetime) -> Directory:
        """Index directory records.

        Records are ordered by corp code; when a corp code repeats, the first record wins.
        When a stock code repeats, ``by_stock_code`` returns the most recently modified
        record (the real directory has no repeats).

        Args:
            records (Iterable[CorpRecord]): Parsed records, usually from parse_directory.
            loaded_at (datetime): When the archive was downloaded.

        Returns:
            Directory: The searchable directory.
        """
        return cls(records, loaded_at=loaded_at)

    def __len__(self) -> int:
        """Count the companies.

        Returns:
            int: Number of records.
        """
        return len(self._codes)

    @property
    def listed_count(self) -> int:
        """Count the companies with a stock code.

        Returns:
            int: Number of listed records.
        """
        return len(self._stock)

    @property
    def loaded_at(self) -> datetime:
        """When the indexed archive was downloaded.

        Returns:
            datetime: Timestamp passed to ``build``.
        """
        return self._loaded_at

    def get(self, corp_code: str) -> CorpRecord | None:
        """Look up a company by corp code.

        Args:
            corp_code (str): 8-digit corp code; surrounding whitespace is ignored.

        Returns:
            CorpRecord | None: The company, or None when the code is unknown or malformed.
        """
        code = corp_code.strip()
        if not is_corp_code(code):
            return None
        position = bisect.bisect_left(self._codes, int(code))
        if position < len(self._codes) and self._codes[position] == int(code):
            return self._record(position)
        return None

    def by_stock_code(self, code: str) -> CorpRecord | None:
        """Look up a company by its 6-character stock code.

        Args:
            code (str): Stock code such as ``005930`` or ``0088M0``, in any case.

        Returns:
            CorpRecord | None: The company, or None when no record has the code.
        """
        position = self._by_stock.get(code.strip().upper())
        return None if position is None else self._record(position)

    def exact(self, text: str) -> tuple[CorpRecord, ...]:
        """Find companies whose Korean or English name equals text after normalization.

        Names compare in compact form, so spacing and legal forms do not matter.

        Args:
            text (str): Company name.

        Returns:
            tuple[CorpRecord, ...]: Matches, listed first, then most recently modified.
        """
        compact = normalize_name(text).replace(" ", "")
        exact_rank = TIER_ORDER.index("exact")
        found: Hits = self._index.exact(compact) if compact else {}
        hits: dict[int, _Hit] = {i: (exact_rank, score, size) for i, (score, size) in found.items()}
        return tuple(self._record(i) for i in sorted(hits, key=lambda i: self._rank(i, hits[i])))

    def search(
        self, query: str, *, listed: bool | None = None, limit: int = 10
    ) -> tuple[Match, ...]:
        """Search companies by code or name; see the class docstring for tiers and ranking.

        Args:
            query (str): Code, or full or partial name in English or Korean.
            listed (bool | None): True for companies with a stock code only, False for
                companies without one only, None for all.
            limit (int): Maximum number of matches, at least 1.

        Returns:
            tuple[Match, ...]: Ranked matches, best first.

        Raises:
            ValueError: limit is less than 1.
        """
        if limit < 1:
            msg = f"limit must be at least 1, got {limit}"
            raise ValueError(msg)
        identifier = parse_identifier(query)
        if identifier is not None:
            return self._code_match(identifier, listed=listed)
        found = self._collect(normalize_name(query), listed=listed, limit=limit)
        best = heapq.nsmallest(limit, found, key=lambda i: self._rank(i, found[i]))
        return tuple(self._match(i, found[i]) for i in best)

    def _collect(self, normalized: str, *, listed: bool | None, limit: int) -> dict[int, _Hit]:
        """Run the name tiers in order until at least ``limit`` companies are found.

        Args:
            normalized (str): Normalized query.
            listed (bool | None): Listing filter.
            limit (int): Number of companies wanted.

        Returns:
            dict[int, _Hit]: Record position to its best hit.
        """
        found: dict[int, _Hit] = {}
        for tier, lookups in _plan(self._index, normalized):
            rank = TIER_ORDER.index(tier)
            for lookup in lookups:
                for position, (score, size) in lookup().items():
                    if position not in found and self._accepts(position, listed=listed):
                        found[position] = (rank, score, size)
            # Later tiers always rank below earlier ones, so stop once the limit is reached.
            if len(found) >= limit:
                break
        return found

    def _code_match(self, identifier: Identifier, *, listed: bool | None) -> tuple[Match, ...]:
        """Answer a code-shaped query.

        Args:
            identifier (Identifier): Parsed query.
            listed (bool | None): Listing filter.

        Returns:
            tuple[Match, ...]: The company with tier ``code``, or nothing.
        """
        if identifier.kind == "corp_code":
            record = self.get(identifier.value)
        elif identifier.kind == "stock_code":
            record = self.by_stock_code(identifier.value)
        else:
            record = None
        if record is None or (listed is not None and record.listed != listed):
            return ()
        return (Match(record, 1.0, "code"),)

    def _accepts(self, position: int, *, listed: bool | None) -> bool:
        """Apply the listing filter.

        Args:
            position (int): Record position.
            listed (bool | None): Listing filter.

        Returns:
            bool: Whether the record passes.
        """
        return listed is None or (position in self._stock) == listed

    def _rank(self, position: int, hit: _Hit) -> _Rank:
        """Build the sort key for a hit.

        Args:
            position (int): Record position.
            hit (_Hit): Tier rank, score, and matched name length.

        Returns:
            _Rank: Tier, unlisted flag, negated score, name length, negated modification
                date, and corp code.
        """
        tier, score, size = hit
        unlisted = 0 if position in self._stock else 1
        return (tier, unlisted, -score, size, -self._modified[position], self._codes[position])

    def _match(self, position: int, hit: _Hit) -> Match:
        """Build a match from a ranked hit.

        Args:
            position (int): Record position.
            hit (_Hit): Tier rank, score, and matched name length.

        Returns:
            Match: The result.
        """
        return Match(self._record(position), min(max(hit[1], 0.0), 1.0), TIER_ORDER[hit[0]])

    def _record(self, position: int) -> CorpRecord:
        """Rebuild a record from the packed columns.

        Args:
            position (int): Record position.

        Returns:
            CorpRecord: The record.
        """
        return CorpRecord(
            corp_code=f"{self._codes[position]:08d}",
            name=self._names.text(position),
            english_name=self._english.text(position) or None,
            stock_code=self._stock.get(position),
            modified=_number_date(self._modified[position]),
        )


def _plan(index: NameIndex, normalized: str) -> _Lookups:
    """Plan the name lookups for a normalized query, grouped by tier.

    Args:
        index (NameIndex): Name index to query.
        normalized (str): Normalized query.

    Returns:
        _Lookups: Tiers in rank order with their deferred lookups.
    """
    compact = normalized.replace(" ", "")
    if not compact:
        return []
    if len(compact) < _MIN_PARTIAL_CHARS:
        return [("exact", (lambda: index.exact(compact),))]
    words = [word for word in normalized.split() if len(word) > 1]
    tokens: tuple[Callable[[], Hits], ...] = (lambda: index.words(words),)
    if has_hangul(compact):
        tokens = (*tokens, lambda: index.korean_substring(compact))
    return [
        ("exact", (lambda: index.exact(compact),)),
        ("prefix", (lambda: index.prefix(compact),)),
        ("token", tokens),
        ("fuzzy", (lambda: index.fuzzy(compact),)),
    ]


def _unique_by_code(records: Iterable[CorpRecord]) -> list[CorpRecord]:
    """Sort records by corp code, keeping the first of repeated codes.

    Args:
        records (Iterable[CorpRecord]): Records in any order.

    Returns:
        list[CorpRecord]: Records with unique corp codes in ascending order.
    """
    ordered = sorted(records, key=lambda record: record.corp_code)  # Stable: first wins.
    return [
        record
        for i, record in enumerate(ordered)
        if i == 0 or record.corp_code != ordered[i - 1].corp_code
    ]


def _date_number(value: date | None) -> int:
    """Encode a date as a YYYYMMDD integer.

    Args:
        value (date | None): Date to encode.

    Returns:
        int: YYYYMMDD, or 0 for None.
    """
    return 0 if value is None else value.year * 10000 + value.month * 100 + value.day


def _number_date(value: int) -> date | None:
    """Decode a YYYYMMDD integer.

    Args:
        value (int): Encoded date, or 0.

    Returns:
        date | None: Decoded date, or None for 0.
    """
    return date(value // 10000, value // 100 % 100, value % 100) if value else None
