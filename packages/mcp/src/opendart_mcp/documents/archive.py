"""Bounded, in-memory unpacking of filing archives and decoding of their members.

Archives come from ``disclosures.document`` as ZIP bytes. Members are read into memory with
size checks before and during decompression; member names are only labels and are never used
as filesystem paths, and nothing is written to disk.
"""

from __future__ import annotations

import io
import zipfile
import zlib
from dataclasses import dataclass

from opendart_mcp.documents.errors import ArchiveTooLargeError, MalformedArchiveError

MIB = 1024 * 1024
_ENCRYPTED_FLAG = 0x1
_READ_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, ValueError)


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Size limits applied before and while unpacking an archive.

    The defaults leave headroom over the largest live sample (9.7 MB expanded).

    Attributes:
        max_compressed_bytes (int): Largest accepted archive. Defaults to 32 MiB.
        max_member_bytes (int): Largest accepted expanded member. Defaults to 32 MiB.
        max_total_bytes (int): Largest accepted total of expanded members. Defaults to 64 MiB.
        max_members (int): Most members accepted. Defaults to 20.
    """

    max_compressed_bytes: int = 32 * MIB
    max_member_bytes: int = 32 * MIB
    max_total_bytes: int = 64 * MIB
    max_members: int = 20


@dataclass(frozen=True, slots=True)
class Member:
    """One expanded archive member.

    Attributes:
        name (str): Member name as stored in the archive; a label, never a path.
        data (bytes): Expanded member bytes.
        compressed_size (int): Stored (compressed) size in bytes.
    """

    name: str
    data: bytes
    compressed_size: int

    @property
    def size(self) -> int:
        """Return the expanded size in bytes.

        Returns:
            int: Length of ``data``.
        """
        return len(self.data)


def read_members(archive: bytes, limits: ArchiveLimits | None = None) -> list[Member]:
    """Expand every file member of a ZIP archive in memory, enforcing size limits.

    Args:
        archive (bytes): ZIP archive bytes.
        limits (ArchiveLimits | None): Limits to enforce. None uses the defaults.

    Returns:
        list[Member]: File members in archive order; directory entries are skipped.

    Raises:
        ArchiveTooLargeError: The archive, a member, the expanded total, or the member count
            exceeds its limit.
        MalformedArchiveError: The bytes are not a readable, unencrypted ZIP archive with at
            least one file.
    """
    limits = limits or ArchiveLimits()
    if len(archive) > limits.max_compressed_bytes:
        raise ArchiveTooLargeError(len(archive), limits.max_compressed_bytes)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as handle:
            infos = _file_infos(handle, limits)
            return _expand(handle, infos, limits)
    except _READ_ERRORS as exc:
        msg = f"Unreadable archive: {type(exc).__name__}"
        raise MalformedArchiveError(msg) from exc


def _file_infos(handle: zipfile.ZipFile, limits: ArchiveLimits) -> list[zipfile.ZipInfo]:
    """List file members and check declared sizes, counts, and encryption.

    Args:
        handle (zipfile.ZipFile): Open archive.
        limits (ArchiveLimits): Limits to enforce.

    Returns:
        list[zipfile.ZipInfo]: File members in archive order.

    Raises:
        ArchiveTooLargeError: Declared sizes or the member count exceed the limits.
        MalformedArchiveError: The archive has no files or an encrypted member.
    """
    infos = [info for info in handle.infolist() if not info.is_dir()]
    if not infos:
        msg = "The archive contains no files"
        raise MalformedArchiveError(msg)
    if len(infos) > limits.max_members:
        raise ArchiveTooLargeError(len(infos), limits.max_members, measure="members")
    if any(info.flag_bits & _ENCRYPTED_FLAG for info in infos):
        msg = "The archive contains an encrypted member"
        raise MalformedArchiveError(msg)
    declared = sum(info.file_size for info in infos)
    largest = max(info.file_size for info in infos)
    if largest > limits.max_member_bytes:
        raise ArchiveTooLargeError(largest, limits.max_member_bytes, measure="member bytes")
    if declared > limits.max_total_bytes:
        raise ArchiveTooLargeError(declared, limits.max_total_bytes, measure="expanded bytes")
    return infos


def _expand(
    handle: zipfile.ZipFile, infos: list[zipfile.ZipInfo], limits: ArchiveLimits
) -> list[Member]:
    """Decompress members with hard caps, since declared sizes can lie.

    Args:
        handle (zipfile.ZipFile): Open archive.
        infos (list[zipfile.ZipInfo]): File members to expand.
        limits (ArchiveLimits): Limits to enforce.

    Returns:
        list[Member]: Expanded members.

    Raises:
        ArchiveTooLargeError: A member or the running total exceeds its limit.
    """
    members: list[Member] = []
    total = 0
    for info in infos:
        with handle.open(info) as stream:
            data = stream.read(limits.max_member_bytes + 1)
        if len(data) > limits.max_member_bytes:
            raise ArchiveTooLargeError(len(data), limits.max_member_bytes, measure="member bytes")
        total += len(data)
        if total > limits.max_total_bytes:
            raise ArchiveTooLargeError(total, limits.max_total_bytes, measure="expanded bytes")
        members.append(Member(info.filename, data, info.compress_size))
    return members


def decode(data: bytes) -> str:
    """Decode member bytes as strict UTF-8, falling back to CP949; declared charsets are ignored.

    KRX pages declare ``euc-kr`` but are UTF-8, so the declaration is not trusted. A UTF-8 byte
    order mark is removed.

    Args:
        data (bytes): Member bytes.

    Returns:
        str: Decoded text; undecodable CP949 bytes become U+FFFD.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp949", errors="replace")
