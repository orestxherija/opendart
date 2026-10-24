"""Company lookup over OpenDART's corporation-code directory.

Parse the ZIP archive returned by ``disclosures.corporation_codes`` with ``parse_directory``,
index the records with ``Directory.build``, then search by code or name, or ``resolve`` a
free-text reference to one company:

    records = parse_directory(archive)
    directory = Directory.build(records, loaded_at=datetime.now(UTC))
    resolution = resolve(directory, "Samsung Electronics")

``Directory.search`` returns ranked ``Match`` values; ``resolve`` returns a ``Resolution``
whose ``reason`` keeps selected, ambiguous, and missing references apart. Parsing is
synchronous and does no I/O beyond reading the bytes it is given; importing this package
starts nothing.
"""

from __future__ import annotations

from opendart_analysis.domain.corpcode import MAX_EXPANDED_BYTES, parse_directory
from opendart_analysis.domain.directory import TIER_ORDER, Directory, Match, MatchTier
from opendart_analysis.domain.records import CorpRecord, DirectoryError
from opendart_analysis.domain.resolver import (
    CANDIDATE_POOL,
    Resolution,
    ResolutionReason,
    company_label,
    resolve,
)

__all__ = [
    "CANDIDATE_POOL",
    "MAX_EXPANDED_BYTES",
    "TIER_ORDER",
    "CorpRecord",
    "Directory",
    "DirectoryError",
    "Match",
    "MatchTier",
    "Resolution",
    "ResolutionReason",
    "company_label",
    "parse_directory",
    "resolve",
]
