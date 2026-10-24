"""Parsing the corporation-code archive."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import date

import pytest

from opendart_analysis.domain.directory import (
    MEMBER_NAME,
    CorpRecord,
    DirectoryError,
    parse_directory,
)


def entry(
    code="00126380",
    name="삼성전자",
    english="SAMSUNG ELECTRONICS CO,.LTD",
    stock="005930",
    modified="20251201",
):
    fields = {
        "corp_code": code,
        "corp_name": name,
        "corp_eng_name": english,
        "stock_code": stock,
        "modify_date": modified,
    }
    return "<list>" + "".join(f"<{tag}>{text}</{tag}>" for tag, text in fields.items()) + "</list>"


def document(*entries):
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<result>{"".join(entries)}</result>'


def test_parses_records_in_archive_order(make_archive, records):
    parsed = parse_directory(make_archive())
    # Whitespace runs collapse: "BNK  3 SPECIAL ..." becomes "BNK 3 SPECIAL ...".
    expected = tuple(
        replace(
            record,
            english_name=" ".join(record.english_name.split()) if record.english_name else None,
        )
        for record in records
    )
    assert parsed == expected
    assert parsed[17].english_name == "BNK 3 SPECIAL PURPOSE ACQUISITION COMPANY"
    assert MEMBER_NAME == "CORPCODE.xml"


def test_fields_are_cleaned(make_archive):
    xml = document(
        entry(),
        entry("00434003", "다코", "Daco corporation", " ", "20170630"),
        entry(
            "01933981",
            " 비엔케이제3호스팩 ",
            "BNK  3\tSPECIAL PURPOSE ACQUISITION COMPANY\t\t",
            "0068y0",
            "20251121",
        ),
        entry("09000001", "한국전장", "한국전장주식회사", "", "2017-06-30"),
        entry("09000002", "에이", "", "1234567", "20250230"),
    )
    parsed = parse_directory(make_archive(xml=xml))
    assert parsed[0] == CorpRecord(
        "00126380", "삼성전자", "SAMSUNG ELECTRONICS CO,.LTD", "005930", date(2025, 12, 1)
    )
    assert parsed[1].stock_code is None
    assert not parsed[1].listed
    assert parsed[2] == CorpRecord(
        "01933981",
        "비엔케이제3호스팩",
        "BNK 3 SPECIAL PURPOSE ACQUISITION COMPANY",
        "0068Y0",
        date(2025, 11, 21),
    )
    assert parsed[2].listed
    assert parsed[3].english_name == "한국전장주식회사"
    assert parsed[3].modified is None
    assert parsed[4].english_name is None
    assert parsed[4].stock_code is None
    assert parsed[4].modified is None


@pytest.mark.parametrize(
    "placeholder",
    [
        "-",
        "",
        ".",
        "..",
        "N",
        "n",
        "N/A",
        "n/a",
        "NA",
        "no entry",
        "None",
        "Not applicable",
        "0",
        "00",
        "_",
        "/",
        "없음",
        "해당없음",
        "해당사항 없음.",
        "없슴",
    ],
)
def test_english_placeholders_become_none(make_archive, placeholder):
    parsed = parse_directory(make_archive(xml=document(entry(english=placeholder))))
    assert parsed[0].english_name is None
    assert parsed[0].display_name == "삼성전자"


def test_shared_modification_dates_are_reused(make_archive):
    xml = document(entry("00000001"), entry("00000002"))
    first, second = parse_directory(make_archive(xml=xml))
    assert first.modified is second.modified


def test_invalid_and_repeated_records_are_skipped(make_archive):
    valid = [entry(f"0000000{digit}") for digit in range(4, 9)]
    xml = document(
        entry("00126380"),
        entry("00126380", "중복"),
        entry("1234567"),
        entry("0012638A"),
        entry("00000003", ""),
        *valid,
        "<list><corp_name>코드없음</corp_name></list>",
        "<other>ignored</other>",
    )
    parsed = parse_directory(make_archive(xml=xml))
    codes = ["00126380", "00000004", "00000005", "00000006", "00000007", "00000008"]
    assert [record.corp_code for record in parsed] == codes
    assert parsed[0].name == "삼성전자"


def test_mostly_invalid_archives_are_rejected(make_archive):
    xml = document(entry("1"), entry("2"), entry("00000003"))
    with pytest.raises(DirectoryError, match="1 valid and 2 invalid"):
        parse_directory(make_archive(xml=xml))


def test_archives_without_records_are_rejected(make_archive):
    xml = "<result><status>013</status><message>No data</message></result>"
    with pytest.raises(DirectoryError, match="0 valid"):
        parse_directory(make_archive(xml=xml))


def test_wrong_root_is_rejected(make_archive):
    with pytest.raises(DirectoryError, match="root element 'html'"):
        parse_directory(make_archive(xml=f"<html>{entry()}</html>"))


@pytest.mark.parametrize(
    "xml",
    [
        '<?xml version="1.0"?><!DOCTYPE result [<!ENTITY x "boom">]><result>&x;</result>',
        '<?xml version="1.0"?><!DOCTYPE result SYSTEM "http://example.com/x.dtd"><result/>',
    ],
)
def test_dtds_and_entities_are_forbidden(make_archive, xml):
    with pytest.raises(DirectoryError, match="not valid XML"):
        parse_directory(make_archive(xml=xml))


@pytest.mark.parametrize("xml", ["<result><list>", "not xml at all", b"<result>\xff\xfe</result>"])
def test_malformed_xml_is_rejected(make_archive, xml):
    with pytest.raises(DirectoryError, match="not valid XML"):
        parse_directory(make_archive(xml=xml))


def test_non_zip_bytes_are_rejected():
    with pytest.raises(DirectoryError, match="unreadable"):
        parse_directory(b"<result><status>020</status></result>")


def test_truncated_zip_is_rejected(make_archive):
    archive = make_archive()
    with pytest.raises(DirectoryError):
        parse_directory(archive[: len(archive) // 2])


def test_corrupt_member_data_is_rejected(make_archive):
    archive = bytearray(make_archive())
    start = archive.index(b"CORPCODE.xml") + len(b"CORPCODE.xml")
    for offset in range(start + 10, start + 40):
        archive[offset] ^= 0xFF
    with pytest.raises(DirectoryError):
        parse_directory(bytes(archive))


def test_member_size_limit_is_enforced(make_archive):
    with pytest.raises(DirectoryError, match="over the 100-byte limit"):
        parse_directory(make_archive(), max_expanded_bytes=100)


def test_another_single_xml_member_is_accepted(make_archive):
    archive = make_archive(members={"directory/codes.XML": document(entry()), "readme/": b""})
    assert len(parse_directory(archive)) == 1


def test_corpcode_member_wins_over_other_xml(make_archive):
    archive = make_archive(members={"other.xml": "<html/>", "CORPCODE.xml": document(entry())})
    assert parse_directory(archive)[0].corp_code == "00126380"


@pytest.mark.parametrize(
    "members",
    [
        {},
        {"notes.txt": "hello"},
        {"a.xml": "<result/>", "b.xml": "<result/>"},
    ],
)
def test_missing_or_ambiguous_members_are_rejected(make_archive, members):
    with pytest.raises(DirectoryError, match=r"Expected one CORPCODE\.xml member"):
        parse_directory(make_archive(members=members))


def test_unsupported_compression_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("CORPCODE.xml", document(entry()))
    data = bytearray(buffer.getvalue())
    # Rewrite the method field (offset 8 in the local header, 10 in the central header) to 99.
    data[8:10] = (99).to_bytes(2, "little")
    central = data.index(b"PK\x01\x02")
    data[central + 10 : central + 12] = (99).to_bytes(2, "little")
    with pytest.raises(DirectoryError, match="unreadable"):
        parse_directory(bytes(data))
