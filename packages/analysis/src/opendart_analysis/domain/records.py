"""Company records from the OpenDART corporation-code directory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


class DirectoryError(Exception):
    """The corporation-code archive is malformed, oversized, or unsafe to parse."""


@dataclass(frozen=True, slots=True)
class CorpRecord:
    """One company from the corporation-code directory.

    The directory has no market field; a stock code means the company has a KRX listing
    code, which delisted companies also keep. The market comes from ``corp_cls`` in
    company and search responses.

    Attributes:
        corp_code (str): 8-digit DART corp code.
        name (str): Formal Korean name (Latin script for some foreign companies).
        english_name (str | None): English name, or None when the directory has none or
            only a placeholder such as ``-`` or ``N/A``.
        stock_code (str | None): 6-character stock code, or None for unlisted companies.
        modified (date | None): When DART last changed the record.
    """

    corp_code: str
    name: str
    english_name: str | None
    stock_code: str | None
    modified: date | None

    @property
    def listed(self) -> bool:
        """Whether the company has a stock code.

        Returns:
            bool: True when a stock code is present.
        """
        return self.stock_code is not None

    @property
    def display_name(self) -> str:
        """English name when available, otherwise the Korean name.

        Returns:
            str: Name for English-language output.
        """
        return self.english_name or self.name
