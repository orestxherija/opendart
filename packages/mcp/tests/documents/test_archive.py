"""Archive unpacking limits, malformed archives, and member decoding."""

from __future__ import annotations

import io
import zipfile

import pytest

from opendart_mcp.documents import (
    ArchiveLimits,
    ArchiveTooLargeError,
    MalformedArchiveError,
    decode,
    read_members,
)
from opendart_mcp.documents.archive import _expand


def test_members_are_read_in_order_and_directories_skipped(zipper):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.mkdir("folder")
        archive.writestr("b.xml", "<b/>")
        archive.writestr("a.xml", "<a/>", compress_type=zipfile.ZIP_STORED)
    members = read_members(buffer.getvalue())
    assert [member.name for member in members] == ["b.xml", "a.xml"]
    assert members[1].size == 4
    assert members[1].compressed_size == 4
    assert read_members(zipper({"x.xml": "x"}), None)[0].data == b"x"


def test_compressed_size_limit(zipper):
    archive = zipper({"a.xml": "a" * 100})
    with pytest.raises(ArchiveTooLargeError, match="compressed bytes") as caught:
        read_members(archive, ArchiveLimits(max_compressed_bytes=10))
    assert caught.value.observed_bytes == len(archive)
    assert caught.value.limit == 10
    assert caught.value.measure == "compressed bytes"


def test_member_count_limit(zipper):
    archive = zipper({f"{index}.xml": "x" for index in range(3)})
    with pytest.raises(ArchiveTooLargeError, match="members") as caught:
        read_members(archive, ArchiveLimits(max_members=2))
    assert caught.value.observed_bytes == 3


def test_declared_member_and_total_limits(zipper):
    archive = zipper({"a.xml": "a" * 50, "b.xml": "b" * 50})
    with pytest.raises(ArchiveTooLargeError, match="member bytes"):
        read_members(archive, ArchiveLimits(max_member_bytes=40))
    with pytest.raises(ArchiveTooLargeError, match="expanded bytes"):
        read_members(archive, ArchiveLimits(max_total_bytes=90))


def test_expansion_caps_hold_even_if_declared_sizes_pass(zipper):
    archive = zipper({"a.xml": "a" * 50, "b.xml": "b" * 50})
    with zipfile.ZipFile(io.BytesIO(archive)) as handle:
        infos = handle.infolist()
        with pytest.raises(ArchiveTooLargeError, match="member bytes"):
            _expand(handle, infos, ArchiveLimits(max_member_bytes=10))
        with pytest.raises(ArchiveTooLargeError, match="expanded bytes"):
            _expand(handle, infos, ArchiveLimits(max_total_bytes=60))


@pytest.mark.parametrize("payload", [b"not a zip", b"PK\x03\x04broken", b""])
def test_unreadable_bytes_are_malformed(payload):
    with pytest.raises(MalformedArchiveError, match="Unreadable archive"):
        read_members(payload)


def test_archives_without_files_are_malformed():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.mkdir("only-a-folder")
    with pytest.raises(MalformedArchiveError, match="no files"):
        read_members(buffer.getvalue())


def test_encrypted_members_are_rejected(zipper):
    archive = bytearray(zipper({"secret.xml": "x"}))
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = archive.index(signature) + flag_offset
        archive[start] |= 0x1  # general-purpose bit 0: encrypted
    with pytest.raises(MalformedArchiveError, match="encrypted"):
        read_members(bytes(archive))


def test_corrupted_member_data_is_malformed(zipper):
    archive = bytearray(zipper({"a.xml": "a" * 200}, method=zipfile.ZIP_STORED))
    offset = archive.index(b"aaaa")
    archive[offset : offset + 4] = b"bbbb"
    with pytest.raises(MalformedArchiveError, match="BadZipFile"):
        read_members(bytes(archive))


def test_decode_prefers_utf8_and_ignores_declared_charset():
    page = '<meta content="text/html; charset=euc-kr"><p>삼성전자</p>'
    assert decode(page.encode()) == page
    assert decode("﻿분기보고서".encode()) == "분기보고서"


def test_decode_falls_back_to_cp949():
    assert decode("삼성전자".encode("cp949")) == "삼성전자"
    assert decode(b"\xff\xfe\xfd") == "���"


def test_error_messages_name_sizes_keys_and_sections():
    from opendart_mcp.documents import (
        DownloadPendingError,
        SectionInfo,
        SectionNotFoundError,
        UnknownDocumentError,
    )

    assert str(ArchiveTooLargeError(40_000_000, 33_554_432)) == (
        "Archive exceeds the compressed bytes limit: 40,000,000 > 33,554,432"
    )
    unknown = UnknownDocumentError(["main", "audit_report"], document="x")
    assert (str(unknown), unknown.document) == (
        "Unknown document 'x'; available: main, audit_report",
        "x",
    )
    assert str(UnknownDocumentError(["main"])) == "Unknown document; available: main"
    info = SectionInfo(id="D-0-1-1-0", level=2, title_ko="회사의 개요", chars=10, tables=0)
    assert str(SectionNotFoundError("company", [info])) == (
        "No section matches 'company'; closest: D-0-1-1-0 (회사의 개요)"
    )
    assert str(SectionNotFoundError("x", [])) == "No section matches 'x'; closest: none"
    pending = DownloadPendingError("20260310002820", 12.4)
    assert str(pending) == "Filing 20260310002820 is still downloading after 12 s; retry shortly"
