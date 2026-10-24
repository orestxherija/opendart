"""Company lookup over OpenDART's corporation-code directory.

Parse the ZIP archive returned by ``disclosures.corporation_codes`` with ``parse_directory``,
index the records with ``Directory.build``, then search by code or name, or ``resolve`` a
free-text reference to one company:

    records = parse_directory(archive)
    directory = Directory.build(records, loaded_at=datetime.now(UTC))
    resolution = resolve(directory, "Samsung Electronics")

``Directory.search`` returns ranked ``Match`` values; ``resolve`` returns a ``Resolution``
whose ``reason`` keeps selected, ambiguous, and missing references apart. Parsing is
synchronous and does no I/O beyond reading the bytes it is given.

Long-running asyncio applications can use ``DirectoryLoader``, which downloads through a
caller-supplied callback, caches the archive on disk, and refreshes it on a schedule, but
only once the caller starts it. Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.directory.loader import (
    RETRY_DELAYS_S,
    DescribeError,
    DirectoryLoader,
    DirectoryNotReadyError,
    FetchArchive,
    LoadFailure,
    LoaderConfig,
    LoaderStatus,
)
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
    "RETRY_DELAYS_S",
    "TIER_ORDER",
    "CorpRecord",
    "DescribeError",
    "Directory",
    "DirectoryError",
    "DirectoryLoader",
    "DirectoryNotReadyError",
    "FetchArchive",
    "LoadFailure",
    "LoaderConfig",
    "LoaderStatus",
    "Match",
    "MatchTier",
    "Resolution",
    "ResolutionReason",
    "company_label",
    "parse_directory",
    "resolve",
]
