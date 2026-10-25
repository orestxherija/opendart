"""Compact name index behind directory search: exact, prefix, word, and fuzzy lookups.

The directory has about 120,000 companies and 240,000 Korean and English names. To keep
the retained index small (about 20 MB), names are packed into UTF-8 blobs (see ``packed``),
record positions into arrays, and lookups binary-search the sorted blobs.

Lookups return record positions with a score and the matched name's length; the directory
turns them into ranked matches.
"""

from __future__ import annotations

import bisect
from array import array
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from opendart_analysis.domain.names import is_hangul, normalize_name
from opendart_analysis.domain.packed import Postings

if TYPE_CHECKING:
    from collections.abc import Sequence

type Hits = dict[int, tuple[float, int]]
"""Record position mapped to (score, matched name length)."""

FUZZY_MIN_RATIO = 0.75
"""Lowest difflib ratio reported as a fuzzy match."""

_SUBSTRING_HIT_CAP = 2000
_FUZZY_DICE_MIN = 0.3
_FUZZY_POOL_TOP = 40
_FUZZY_WINDOW = 400


def _bigrams(text: str) -> set[str]:
    """Collect the character bigrams of a compact name.

    Args:
        text (str): Compact name.

    Returns:
        set[str]: Distinct bigrams; a single character counts as its own bigram.
    """
    return {text[i : i + 2] for i in range(max(len(text) - 1, 1))}


@dataclass(frozen=True, slots=True)
class _FuzzyPool:
    """Listed companies' names with a bigram index for fast fuzzy candidate selection.

    Attributes:
        names (tuple[str, ...]): Compact names.
        owners (array[int]): Record position per name.
        sizes (array[int]): Distinct bigram count per name.
        postings (dict[str, array[int]]): Bigram to name positions.
    """

    names: tuple[str, ...]
    owners: array[int]
    sizes: array[int]
    postings: dict[str, array[int]]

    @classmethod
    def build(cls, names: list[str], owners: array[int]) -> _FuzzyPool:
        """Index compact names by bigram.

        Args:
            names (list[str]): Compact names.
            owners (array[int]): Record position per name.

        Returns:
            _FuzzyPool: Pool ready for candidate selection.
        """
        postings: dict[str, array[int]] = {}
        sizes = array("I")
        for position, name in enumerate(names):
            grams = _bigrams(name)
            sizes.append(len(grams))
            for gram in grams:
                postings.setdefault(gram, array("I")).append(position)
        return cls(tuple(names), owners, sizes, postings)

    def candidates(self, text: str) -> list[tuple[str, int]]:
        """Select the names sharing the most bigrams with text (Dice coefficient).

        Args:
            text (str): Compact query.

        Returns:
            list[tuple[str, int]]: Up to 40 (name, record position) pairs, best first.
        """
        grams = _bigrams(text)
        shared: Counter[int] = Counter()
        for gram in grams:
            shared.update(self.postings.get(gram, ()))
        ranked = sorted(
            (-2 * count / (len(grams) + self.sizes[position]), position)
            for position, count in shared.items()
        )
        best = [position for dice, position in ranked[:_FUZZY_POOL_TOP] if -dice >= _FUZZY_DICE_MIN]
        return [(self.names[position], self.owners[position]) for position in best]


class NameIndex:
    """Searchable Korean and English names for every directory record.

    Records are identified by their position in the sequences passed to ``build``.
    """

    __slots__ = ("_fuzzy", "_korean", "_lengths", "_names", "_words")

    def __init__(self, builder: _Builder) -> None:
        """Pack a filled builder; use ``build`` instead.

        Args:
            builder (_Builder): Normalized names of every record.
        """
        self._names = builder.pack_names()
        self._words = Postings(sorted(builder.words.items()))
        builder.words.clear()
        self._korean = _KoreanNames(
            builder.listed_korean + builder.unlisted_korean,
            builder.listed_korean_owners + builder.unlisted_korean_owners,
        )
        self._fuzzy = _FuzzyPool.build(builder.pool, builder.pool_owners)
        self._lengths = builder.lengths

    @classmethod
    def build(
        cls, names: Sequence[str], english: Sequence[str | None], listed: Sequence[bool]
    ) -> NameIndex:
        """Normalize and index every record's names.

        Args:
            names (Sequence[str]): Korean name per record.
            english (Sequence[str | None]): English name per record.
            listed (Sequence[bool]): Whether each record has a stock code.

        Returns:
            NameIndex: Index over the records.
        """
        builder = _Builder()
        for position, (name, english_name) in enumerate(zip(names, english, strict=True)):
            builder.add(position, name, english_name, listed=listed[position])
        return cls(builder)

    def exact(self, compact: str) -> Hits:
        """Find records whose compact name equals the query.

        Args:
            compact (str): Compact normalized query.

        Returns:
            Hits: Matching records with score 1.
        """
        return {
            owner: (1.0, len(compact))
            for index in self._names.equal(compact)
            for owner in self._names.owners_of(index)
        }

    def prefix(self, compact: str) -> Hits:
        """Find records whose compact name starts with the query.

        Args:
            compact (str): Compact normalized query, at least two characters.

        Returns:
            Hits: Records scored by the share of the name the query covers.
        """
        hits: Hits = {}
        for index in self._names.starting(compact):
            size = len(self._names.names.text(index))
            for owner in self._names.owners_of(index):
                if len(compact) / size > hits.get(owner, (0.0, 0))[0]:
                    hits[owner] = (len(compact) / size, size)
        return hits

    def words(self, words: Sequence[str]) -> Hits:
        """Find records with a word starting with each query word, in any order.

        Only names of two or more words are indexed by word; single-word names are fully
        covered by the prefix lookup.

        Args:
            words (Sequence[str]): Query words of at least two characters.

        Returns:
            Hits: Records scored by the share of their compact name the query covers.
        """
        common: set[int] | None = None
        for word in sorted(words, key=len, reverse=True):
            found = {
                owner
                for index in self._words.starting(word)
                for owner in self._words.owners_of(index)
            }
            common = found if common is None else common & found
            if not common:
                return {}
        covered = sum(len(word) for word in words)
        return {owner: self._coverage(covered, owner) for owner in common or ()}

    def korean_substring(self, compact: str) -> Hits:
        """Find records whose compact Korean name contains the query.

        Args:
            compact (str): Compact query, at least two characters.

        Returns:
            Hits: Records scored by the share of the Korean name the query covers.
        """
        return self._korean.containing(compact)

    def fuzzy(self, compact: str) -> Hits:
        """Find records whose compact name is similar to the query.

        Candidates are listed companies sharing character bigrams with the query, plus any
        company whose name sorts near the query and shares its first characters (three,
        or two when the query starts with Hangul). Scores are difflib ratios of at least
        ``FUZZY_MIN_RATIO``.

        Args:
            compact (str): Compact normalized query, at least two characters.

        Returns:
            Hits: Records scored by similarity.
        """
        matcher = SequenceMatcher(None, autojunk=False)
        matcher.set_seq2(compact)
        hits: Hits = {}
        for name, owner in (*self._fuzzy.candidates(compact), *self._neighbors(compact)):
            matcher.set_seq1(name)
            if (
                matcher.real_quick_ratio() < FUZZY_MIN_RATIO
                or matcher.quick_ratio() < FUZZY_MIN_RATIO
            ):
                continue
            score = matcher.ratio()
            if score >= FUZZY_MIN_RATIO and score > hits.get(owner, (0.0, 0))[0]:
                hits[owner] = (score, len(name))
        return hits

    def _neighbors(self, compact: str) -> list[tuple[str, int]]:
        """List names that share the query's first characters and sort near it.

        Args:
            compact (str): Compact normalized query.

        Returns:
            list[tuple[str, int]]: (name, record position) pairs from up to 800 names.
        """
        span = self._names.starting(compact[: 2 if is_hangul(compact[0]) else 3])
        names = self._names.names
        middle = bisect.bisect_left(names, compact.encode(), span.start, span.stop)
        window = range(
            max(span.start, middle - _FUZZY_WINDOW), min(span.stop, middle + _FUZZY_WINDOW)
        )
        return [(names.text(i), owner) for i in window for owner in self._names.owners_of(i)]

    def _coverage(self, covered: int, owner: int) -> tuple[float, int]:
        """Score a word match by the share of the record's compact name covered.

        Args:
            covered (int): Characters in the query words.
            owner (int): Record position.

        Returns:
            tuple[float, int]: Score at most 1 and the record's compact name length.
        """
        size = self._lengths[owner]
        return min(covered / size, 1.0) if size else 0.0, size


class _KoreanNames:
    """Compact Korean names joined into one string for fast substring search.

    Listed companies come first, so the hit cap only ever drops unlisted companies.
    """

    __slots__ = ("_joined", "_owners", "_starts")

    def __init__(self, names: list[str], owners: array[int]) -> None:
        """Join names, listed companies first.

        Args:
            names (list[str]): Compact Korean names, listed companies first.
            owners (array[int]): Record position per name.
        """
        self._joined = "".join(f"{name}\n" for name in names)
        self._starts = array("I", [0])
        for name in names:
            self._starts.append(self._starts[-1] + len(name) + 1)
        self._owners = owners

    def containing(self, compact: str) -> Hits:
        """Find names containing the query, at most 2,000.

        Args:
            compact (str): Compact query without line breaks.

        Returns:
            Hits: Records scored by the share of the name the query covers.
        """
        hits: Hits = {}
        found = self._joined.find(compact)
        while found >= 0 and len(hits) < _SUBSTRING_HIT_CAP:
            slot = bisect.bisect_right(self._starts, found) - 1
            size = self._starts[slot + 1] - self._starts[slot] - 1
            hits[self._owners[slot]] = (len(compact) / size, size)
            found = self._joined.find(compact, self._starts[slot + 1])
        return hits


class _Builder:
    """Accumulate normalized names before sorting and packing them.

    Attributes:
        names (list[str]): Compact names, parallel to name_owners.
        name_owners (array[int]): Record position per compact name.
        words (dict[str, array[int]]): Word of a multi-word name to record positions.
        listed_korean (list[str]): Listed companies' compact Korean names.
        listed_korean_owners (array[int]): Record position per listed Korean name.
        unlisted_korean (list[str]): Other companies' compact Korean names.
        unlisted_korean_owners (array[int]): Record position per unlisted Korean name.
        pool (list[str]): Listed companies' compact names for fuzzy matching.
        pool_owners (array[int]): Record position per pool name.
        lengths (array[int]): Compact English (else Korean) name length per record.
    """

    def __init__(self) -> None:
        """Start empty."""
        self.names: list[str] = []
        self.name_owners = array("I")
        self.words: dict[str, array[int]] = {}
        self.listed_korean: list[str] = []
        self.listed_korean_owners = array("I")
        self.unlisted_korean: list[str] = []
        self.unlisted_korean_owners = array("I")
        self.pool: list[str] = []
        self.pool_owners = array("I")
        self.lengths = array("I")

    def add(self, position: int, name: str, english: str | None, *, listed: bool) -> None:
        """Normalize and record one company's names.

        Args:
            position (int): Record position.
            name (str): Korean name.
            english (str | None): English name.
            listed (bool): Whether the company has a stock code.
        """
        korean = self._add_name(position, name)
        latin = self._add_name(position, english, skip=korean) if english else ""
        self.lengths.append(len(latin or korean))
        if not listed:
            self.unlisted_korean.append(korean)
            self.unlisted_korean_owners.append(position)
            return
        self.listed_korean.append(korean)
        self.listed_korean_owners.append(position)
        for compact in dict.fromkeys(item for item in (korean, latin) if item):
            self.pool.append(compact)
            self.pool_owners.append(position)

    def pack_names(self) -> Postings:
        """Sort and pack the compact names, then release the builder's copies.

        Returns:
            Postings: Distinct compact names with their record positions.
        """
        postings = Postings.from_pairs(self.names, self.name_owners)
        self.names.clear()
        del self.name_owners[:]
        return postings

    def _add_name(self, position: int, text: str, *, skip: str = "") -> str:
        """Index one name unless its compact form repeats another of the record's names.

        Args:
            position (int): Record position.
            text (str): Name.
            skip (str): Compact name already indexed for the record.

        Returns:
            str: Compact form of the name.
        """
        normalized = normalize_name(text)
        compact = normalized.replace(" ", "")
        if compact and compact != skip:
            self.names.append(compact)
            self.name_owners.append(position)
        words = normalized.split()
        if len(words) > 1:
            for word in dict.fromkeys(words):
                postings = self.words.setdefault(word, array("I"))
                if not postings or postings[-1] != position:
                    postings.append(position)
        return compact
