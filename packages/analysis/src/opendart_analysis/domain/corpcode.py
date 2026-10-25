"""Stream-parse OpenDART's corporation-code ZIP into company records.

The archive holds one member, ``CORPCODE.xml`` (about 30 MB expanded, 120,000 ``<list>``
records under ``<result>``). Parsing streams from the ZIP member with defusedxml, which
forbids DTDs and entities, and clears each record after reading it, so memory stays flat.
"""

from __future__ import annotations

import io
import re
import zipfile
import zlib
from contextlib import contextmanager
from datetime import date
from typing import IO, TYPE_CHECKING
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import iterparse  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

from opendart_analysis.domain.records import CorpRecord, DirectoryError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from xml.etree.ElementTree import Element

MEMBER_NAME = "CORPCODE.xml"
"""Name of the XML member in OpenDART's archive."""

MAX_EXPANDED_BYTES = 64 * 2**20
"""Default limit on the expanded XML size."""

_CORP_CODE = re.compile(r"[0-9]{8}")
_STOCK_CODE = re.compile(r"[0-9A-Z]{6}")
_MODIFIED = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})")
_NOT_WORD = re.compile(r"[\W_]+")
# English-name placeholders seen in the directory, compared without punctuation or spaces.
_PLACEHOLDERS = frozenset(
    {"", "0", "00", "n", "na", "nil", "none", "noentry", "notapplicable"}
    | {"없음", "없슴", "해당없음", "해당사항없음"}
)
# Failures while reading a corrupt member: CRC or header errors, truncated or corrupt
# deflate data, unsupported compression or encryption, and malformed or unsafe XML.
_ARCHIVE_ERRORS = (
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    OSError,
    NotImplementedError,
    RuntimeError,
    ParseError,
    DefusedXmlException,
)


def parse_directory(
    archive: bytes, *, max_expanded_bytes: int = MAX_EXPANDED_BYTES
) -> tuple[CorpRecord, ...]:
    """Parse the corporation-code archive into records.

    Records without a valid 8-digit corp code or a name are skipped, as are repeated corp
    codes after their first occurrence. English placeholders such as ``-``, ``N/A``, or
    ``없음`` become None, blank stock codes become None, and whitespace runs (including
    tabs) collapse to single spaces.

    Args:
        archive (bytes): ZIP bytes as downloaded from ``corpCode.xml``.
        max_expanded_bytes (int): Largest accepted size of the expanded XML member.

    Returns:
        tuple[CorpRecord, ...]: Records in archive order.

    Raises:
        DirectoryError: The bytes are not a readable ZIP, the XML member is missing or
            larger than the limit, the XML is malformed or uses DTDs or entities, the root
            is not ``result``, or most records are invalid.
    """
    with _open_member(archive, max_expanded_bytes) as stream:
        try:
            return _read_records(stream)
        except _ARCHIVE_ERRORS as error:
            msg = f"The company directory archive is not valid XML: {error}"
            raise DirectoryError(msg) from error


@contextmanager
def _open_member(archive: bytes, max_expanded_bytes: int) -> Iterator[IO[bytes]]:
    """Open the XML member of the archive after checking its declared size.

    Args:
        archive (bytes): ZIP bytes.
        max_expanded_bytes (int): Largest accepted expanded size.

    Yields:
        IO[bytes]: Decompressing stream over the member.

    Raises:
        DirectoryError: The archive is unreadable, or the member is missing or too large.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            info = _select_member(bundle.infolist())
            if info.file_size > max_expanded_bytes:
                msg = f"The company directory expands to {info.file_size} bytes, over the {max_expanded_bytes}-byte limit"
                raise DirectoryError(msg)
            with bundle.open(info) as stream:
                yield stream
    except _ARCHIVE_ERRORS as error:
        msg = f"The company directory archive is unreadable: {error}"
        raise DirectoryError(msg) from error


def _select_member(infos: list[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    """Choose ``CORPCODE.xml``, or the only XML member when the name differs.

    Args:
        infos (list[zipfile.ZipInfo]): Archive members.

    Returns:
        zipfile.ZipInfo: Member to parse.

    Raises:
        DirectoryError: No member, or several candidates without ``CORPCODE.xml``.
    """
    files = [info for info in infos if not info.is_dir()]
    named = [info for info in files if info.filename.rsplit("/", 1)[-1].upper() == "CORPCODE.XML"]
    xml = [info for info in files if info.filename.lower().endswith(".xml")]
    candidates = named or xml
    if len(candidates) != 1:
        msg = f"Expected one {MEMBER_NAME} member in the company directory archive, found {len(candidates)}"
        raise DirectoryError(msg)
    return candidates[0]


def _read_records(stream: IO[bytes]) -> tuple[CorpRecord, ...]:
    """Stream ``<list>`` records from the XML member.

    Args:
        stream (IO[bytes]): XML byte stream.

    Returns:
        tuple[CorpRecord, ...]: Valid records in document order.

    Raises:
        DirectoryError: The root is not ``result`` or most records are invalid.
    """
    builder = _RecordBuilder()
    root: Element | None = None
    events = iterparse(stream, events=("start", "end"), forbid_dtd=True)
    for event, element in events:
        if root is None:
            root = element
            if element.tag != "result":
                msg = f"Unexpected company directory root element {element.tag!r}"
                raise DirectoryError(msg)
        elif event == "end" and element.tag == "list":
            builder.add({child.tag: child.text or "" for child in element})
            root.clear()
    return builder.finish()


class _RecordBuilder:
    """Validate raw ``<list>`` fields into records, sharing repeated date objects."""

    def __init__(self) -> None:
        """Start with no records."""
        self.records: list[CorpRecord] = []
        self.invalid = 0
        self._seen: set[str] = set()
        self._dates: dict[str, date | None] = {}

    def add(self, fields: dict[str, str]) -> None:
        """Convert one record, or count it as invalid.

        Args:
            fields (dict[str, str]): Child element texts by tag.
        """
        corp_code = fields.get("corp_code", "").strip()
        name = " ".join(fields.get("corp_name", "").split())
        if not _CORP_CODE.fullmatch(corp_code) or not name or corp_code in self._seen:
            self.invalid += 1
            return
        self._seen.add(corp_code)
        stock_code = fields.get("stock_code", "").strip().upper()
        self.records.append(
            CorpRecord(
                corp_code=corp_code,
                name=name,
                english_name=_english_name(fields.get("corp_eng_name", "")),
                stock_code=stock_code if _STOCK_CODE.fullmatch(stock_code) else None,
                modified=self._date(fields.get("modify_date", "").strip()),
            )
        )

    def finish(self) -> tuple[CorpRecord, ...]:
        """Return the records, rejecting archives that are mostly invalid.

        Returns:
            tuple[CorpRecord, ...]: Valid records.

        Raises:
            DirectoryError: There are no valid records, or invalid ones outnumber them.
        """
        if not self.records or self.invalid > len(self.records):
            msg = f"The company directory has {len(self.records)} valid and {self.invalid} invalid records"
            raise DirectoryError(msg)
        return tuple(self.records)

    def _date(self, text: str) -> date | None:
        """Parse a ``YYYYMMDD`` modification date, reusing earlier results.

        Args:
            text (str): Date text.

        Returns:
            date | None: Parsed date, or None when invalid.
        """
        if text not in self._dates:
            self._dates[text] = _yyyymmdd(text)
        return self._dates[text]


def _yyyymmdd(text: str) -> date | None:
    """Parse ``YYYYMMDD``.

    Args:
        text (str): Date text.

    Returns:
        date | None: Parsed date, or None when the text is not a valid date.
    """
    match = _MODIFIED.fullmatch(text)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _english_name(text: str) -> str | None:
    """Clean an English name, mapping placeholders to None.

    Args:
        text (str): Raw English name.

    Returns:
        str | None: Name with collapsed whitespace, or None for placeholders.
    """
    name = " ".join(text.split())
    if _NOT_WORD.sub("", name).casefold() in _PLACEHOLDERS:
        return None
    return name
