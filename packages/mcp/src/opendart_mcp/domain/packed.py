"""Memory-compact string storage for the directory index.

About 240,000 company names as individual Python strings would cost tens of megabytes, so
the index packs them into one UTF-8 blob with an offset array. UTF-8 byte order equals code
point order, so packed sorted strings can be searched with ``bisect`` on their bytes.
"""

from __future__ import annotations

import bisect
from array import array
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_UTF8_MAX = b"\xff"  # Sorts after every UTF-8 sequence, closing prefix ranges.


class PackedStrings:
    """Immutable sequence of strings stored as one UTF-8 blob with offsets.

    Indexing returns the UTF-8 bytes, which ``bisect`` can compare directly; ``text``
    decodes one item.
    """

    __slots__ = ("_blob", "_offsets")

    def __init__(self, items: Iterable[str]) -> None:
        """Pack strings in the given order.

        Args:
            items (Iterable[str]): Strings to store.
        """
        blob = bytearray()
        self._offsets = array("I", [0])
        for item in items:
            blob += item.encode()
            self._offsets.append(len(blob))
        self._blob = bytes(blob)

    def __len__(self) -> int:
        """Count the stored strings.

        Returns:
            int: Number of items.
        """
        return len(self._offsets) - 1

    def __getitem__(self, index: int) -> bytes:
        """Return one item as UTF-8 bytes.

        Args:
            index (int): Item position, from 0.

        Returns:
            bytes: Encoded item.
        """
        return self._blob[self._offsets[index] : self._offsets[index + 1]]

    def text(self, index: int) -> str:
        """Return one item as a string.

        Args:
            index (int): Item position, from 0.

        Returns:
            str: Decoded item.
        """
        return self[index].decode()


class Postings:
    """Distinct sorted strings, each with the record positions that carry it.

    Attributes:
        names (PackedStrings): Distinct strings in sorted order.
        starts (array[int]): Offset of each string's positions in owners, plus the end.
        owners (array[int]): Record positions, grouped by string.
    """

    __slots__ = ("names", "owners", "starts")

    def __init__(self, groups: Iterable[tuple[str, Iterable[int]]]) -> None:
        """Pack groups given in sorted order of their strings.

        Args:
            groups (Iterable[tuple[str, Iterable[int]]]): String and its record positions.
        """
        self.starts = array("I", [0])
        self.owners = array("I")
        self.names = PackedStrings(self._pack(groups))

    @classmethod
    def from_pairs(cls, names: list[str], owners: array[int]) -> Postings:
        """Sort parallel (string, record position) lists and pack them.

        Args:
            names (list[str]): Strings, possibly repeated.
            owners (array[int]): Record position per string.

        Returns:
            Postings: Distinct strings with their record positions.
        """
        order = sorted(range(len(names)), key=names.__getitem__)
        return cls(_groups(names, owners, order))

    def equal(self, text: str) -> range:
        """Find the string equal to text.

        Args:
            text (str): String to find.

        Returns:
            range: Zero or one string positions.
        """
        key = text.encode()
        low = bisect.bisect_left(self.names, key)
        return range(low, bisect.bisect_right(self.names, key, low))

    def starting(self, text: str) -> range:
        """Find the strings starting with text.

        Args:
            text (str): Prefix.

        Returns:
            range: String positions in sorted order.
        """
        key = text.encode()
        low = bisect.bisect_left(self.names, key)
        return range(low, bisect.bisect_left(self.names, key + _UTF8_MAX, low))

    def owners_of(self, index: int) -> array[int]:
        """Return the record positions carrying one string.

        Args:
            index (int): String position.

        Returns:
            array[int]: Record positions.
        """
        return self.owners[self.starts[index] : self.starts[index + 1]]

    def _pack(self, groups: Iterable[tuple[str, Iterable[int]]]) -> Iterable[str]:
        """Record each group's positions while yielding its string.

        Args:
            groups (Iterable[tuple[str, Iterable[int]]]): String and its record positions.

        Yields:
            str: Each group's string, in order.
        """
        for name, owners in groups:
            self.owners.extend(owners)
            self.starts.append(len(self.owners))
            yield name


def _groups(
    names: list[str], owners: array[int], order: list[int]
) -> Iterable[tuple[str, list[int]]]:
    """Group sorted strings with the record positions that carry them.

    Args:
        names (list[str]): Strings in insertion order.
        owners (array[int]): Record position per string.
        order (list[int]): String positions in sorted order.

    Yields:
        tuple[str, list[int]]: Distinct string and its record positions.
    """
    current: str | None = None
    group: list[int] = []
    for index in order:
        if names[index] != current:
            if current is not None:
                yield current, group
            current = names[index]
            group = []
        group.append(owners[index])
    if current is not None:
        yield current, group
