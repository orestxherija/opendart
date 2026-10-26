"""Version-bump levels, classified changes, and where in a schema a comparison happens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Final, Literal

from opendart_mcp.versioning.model import canonical

if TYPE_CHECKING:
    from collections.abc import Iterable

type Mode = Literal["input", "output"]

ABSENT: Final = object()
"""Marks a keyword or value that is not present, distinct from JSON null."""
_SHOW_LIMIT: Final = 60


class Level(IntEnum):
    """Version bump a change needs, ordered from none to MAJOR."""

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


@dataclass(frozen=True, slots=True)
class Change:
    """One classified difference.

    Attributes:
        level (Level): Version bump the change needs.
        path (str): Where it is, such as ``inputSchema.limit`` or ``description``.
        detail (str): What changed.
    """

    level: Level
    path: str
    detail: str

    def __str__(self) -> str:
        """Render the change for messages.

        Returns:
            str: ``path: detail``.
        """
        return f"{self.path}: {self.detail}"


@dataclass(frozen=True, slots=True)
class At:
    """Where a schema comparison happens and which kind of schema it compares.

    Attributes:
        mode (Mode): ``input`` for what clients send, ``output`` for what they receive.
        path (str): Location for messages.
    """

    mode: Mode
    path: str

    def below(self, suffix: str) -> At:
        """Descend into a child location.

        Args:
            suffix (str): Path suffix such as ``.name`` or ``[]``.

        Returns:
            At: Child location.
        """
        return At(self.mode, self.path + suffix)

    def change(self, level: Level, detail: str) -> Change:
        """Record a change here.

        Args:
            level (Level): Bump the change needs.
            detail (str): What changed.

        Returns:
            Change: The change.
        """
        return Change(level, self.path, detail)

    def values(self, *, narrows: bool) -> Level:
        """Level of a change to the accepted values that is not a type change.

        Args:
            narrows (bool): The change accepts fewer values.

        Returns:
            Level: MAJOR for narrowed input, MINOR otherwise.
        """
        return Level.MAJOR if self.mode == "input" and narrows else Level.MINOR

    def unknown(self) -> Level:
        """Level of a change that cannot be interpreted, erring toward the larger bump.

        Returns:
            Level: MAJOR for input schemas, MINOR for output schemas.
        """
        return Level.MAJOR if self.mode == "input" else Level.MINOR


def required_level(changes: Iterable[Change]) -> Level:
    """Return the largest bump a set of changes needs.

    Args:
        changes (Iterable[Change]): Classified changes.

    Returns:
        Level: Highest level, or NONE without changes.
    """
    return max((change.level for change in changes), default=Level.NONE)


def show(value: object) -> str:
    """Render a value briefly for messages.

    Args:
        value (object): JSON value, or ``ABSENT``.

    Returns:
        str: Canonical JSON, shortened; ``none`` when absent.
    """
    if value is ABSENT:
        return "none"
    text = canonical(value)
    return text if len(text) <= _SHOW_LIMIT else text[: _SHOW_LIMIT - 3] + "..."
