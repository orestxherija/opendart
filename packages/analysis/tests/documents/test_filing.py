"""parse_filing: outlines, documents, notes, amendments, section resolution, and errors."""

from __future__ import annotations

import pytest

from opendart_analysis.documents import (
    ALIAS_NAMES,
    MalformedArchiveError,
    SectionNotFoundError,
    UnknownDocumentError,
    dart_url,
    parse_filing,
)

FILING = "20260515003117"

OUTLINE = [
    ("COVER", 1, None, "Quarterly Report", 2, False, False),
    ("TTL_CEO_CERT", 1, None, "【Confirmation by CEO, etc.】", 0, False, True),
    ("s3", 1, None, "I. Company Overview", 1, False, False),
    ("D-0-1-1-0", 2, "s3", "1. Company overview", 0, False, False),
    ("D-0-1-3-0", 2, "s3", "3. Changes in capital stock", 0, True, False),
    ("D-0-1-4-0", 2, "s3", "4. Total number of shares, etc.", 1, False, False),
    ("D-0-2-0-0", 1, None, "II. Business Description", 0, False, False),
    (
        "L-0-2-5-L1",
        2,
        "D-0-2-0-0",
        "5. Risk management and derivatives transactions",
        0,
        False,
        False,
    ),
    ("D-0-3-0-0", 1, None, "III. Financial Matters", 2, False, False),
    ("D-0-3-2-0", 2, "D-0-3-0-0", "2. Consolidated financial statements", 1, False, False),
    ("s32", 3, "D-0-3-2-0", "2-1. Consolidated Statement Of FinancialPosition", 1, False, False),
    (
        "D-0-3-3-0",
        2,
        "D-0-3-0-0",
        "3. Notes to the consolidated financial statements",
        1,
        False,
        False,
    ),
    ("s34", 3, "D-0-3-3-0", "1. Corporate information (Consolidated)", 0, False, False),
    ("s35", 3, "D-0-3-3-0", "2. Borrowings (Consolidated)", 1, False, False),
    (
        "D-0-4-0-0",
        1,
        None,
        "IV. Director\u2019s Management Assessment and Analysis Opinion",
        0,
        True,
        False,
    ),
    ("D-0-4-1-0", 2, "D-0-4-0-0", "1. Forward-Looking Statements", 0, True, False),
    ("D-0-11-0-0", 1, None, "XI. Other Matters Necessary for Investor Protection", 0, False, False),
    ("p7.1", 2, "D-0-11-0-0", "【Details】", 0, False, False),
    ("p7.1.1", 3, "p7.1", "1. Overview", 0, False, False),
    ("p7.1.2", 3, "p7.1", "2. Overview", 0, False, False),
    ("D-0-11-4-0", 2, "D-0-11-0-0", "4. Other matters", 0, False, False),
    ("D-0-11-4-0~2", 2, "D-0-11-0-0", "4. Duplicate", 0, False, False),
]


@pytest.fixture
def parsed(periodic_archive):
    return parse_filing(FILING, periodic_archive)


def test_outline_golden(parsed):
    outline = parsed.outline()
    assert [
        (s.id, s.level, s.parent_id, s.title_en, s.tables, s.placeholder, s.image_only)
        for s in outline.sections
    ] == OUTLINE
    assert all(info.chars == len(parsed.section_markdown(info.id)) for info in outline.sections)
    assert [(s.alias, s.section_ids) for s in outline.suggested_sections] == [
        ("company_overview", ["D-0-1-1-0"]),
        ("share_capital", ["D-0-1-3-0", "D-0-1-4-0"]),
        ("business", ["D-0-2-0-0"]),
        ("risk_and_derivatives", ["L-0-2-5-L1"]),
        ("consolidated_statements", ["D-0-3-2-0"]),
        ("consolidated_notes", ["D-0-3-3-0"]),
        ("mdna", ["D-0-4-0-0"]),
        ("subsequent_events", ["D-0-11-4-0"]),
    ]
    assert outline.notes == [
        "Sections TTL_CEO_CERT contain only images, which the archive does not include.",
        "MD&A sections (D-0-4-*) only carry an omission statement in semi-annual and quarterly reports; the full MD&A is in the annual report.",
    ]
    assert outline.amendment is None
    assert outline.model_dump()["documents"] == [
        {
            "key": "main",
            "form_code": "11013",
            "name_en": "Quarterly Report",
            "name_ko": "분기보고서",
            "chars": parsed.documents[0].chars,
            "member": f"{FILING}.xml",
            "size_bytes": parsed.documents[0].size_bytes,
            "rendered": True,
        }
    ]


def test_filing_metadata(parsed):
    assert (parsed.filing_number, parsed.format, parsed.form_code) == (FILING, "dart_xml", "11013")
    assert (parsed.form_name_en, parsed.form_name_ko, parsed.title) == (
        "Quarterly Report",
        "분기보고서",
        "분기보고서",
    )
    assert (parsed.company_name, parsed.corp_code) == ("테스트전자(주)", "00999999")
    assert (
        parsed.dart_url
        == dart_url(FILING)
        == (f"https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo={FILING}")
    )
    english = parsed.rendered_chars
    parsed.read(labels="korean")
    parsed.read(labels="korean")
    assert parsed.rendered_chars > english
    assert parsed.tree().form_code == "11013"


def test_annual_report_with_attachments(annual_archive):
    parsed = parse_filing("20260310002820", annual_archive)
    assert [(d.key, d.form_code, d.name_en, d.name_ko) for d in parsed.documents] == [
        ("main", "11011", "Annual Report", "사업보고서"),
        ("audit_report", "00760", "Audit Report", "감사보고서"),
        ("consolidated_audit_report", "00761", "Consolidated Audit Report", "연결감사보고서"),
    ]
    notes = parsed.outline().notes
    assert notes[0].startswith("The API archive omits attachments the DART website shows")
    assert notes[0].endswith(
        "view them at https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo=20260310002820."
    )
    assert not any("MD&A" in note for note in notes)
    audit = parsed.outline("00760")
    assert audit.document == "audit_report"
    assert [s.id for s in audit.sections] == ["s1", "D-0-0-1-0"]
    assert audit.suggested_sections == []
    assert parsed.outline("20260310002820_00761.xml").document == "consolidated_audit_report"
    assert parsed.resolve_section("audit", document="audit_report").id == "s1"
    assert parsed.resolve_section("Independent", document="audit_report").id == "D-0-0-1-0"
    with pytest.raises(UnknownDocumentError) as caught:
        parsed.outline("attachment")
    assert caught.value.available == ["main", "audit_report", "consolidated_audit_report"]


def test_amendment_summary(amended_archive):
    parsed = parse_filing("20261022000506", amended_archive)
    amendment = parsed.amendment
    assert amendment is not None
    assert (amendment.original_filed, amendment.corrected_document, amendment.section_id) == (
        "2026-10-20",
        "주요사항보고서(전환사채권 발행결정)",
        "CORRECTION",
    )
    first, second = amendment.changes
    assert first.model_dump() == {
        "item": "9-1. 옵션에 관한 사항",
        "reason": "인수계약서 수정",
        "before": "15일이 경과한 날",
        "after": "10영업일이 경과한 날\n(변경)",
    }
    assert second.reason == "인수계약서 수정"
    assert len(second.before) <= 601
    assert second.before.endswith("문장…")
    outline = parsed.outline()
    assert outline.amendment == amendment
    assert outline.notes[-1].startswith("This filing corrects an earlier one")
    assert (
        parsed.form_name_en == "Report on Major Issues (Decision on Issuance of Convertible Bonds)"
    )


def test_krx_filings(zipper, krx_adhoc):
    parsed = parse_filing("20261022800677", zipper({"20261022800677.xml": krx_adhoc}))
    assert (parsed.format, parsed.form_code, parsed.form_name_en) == ("krx_html", None, None)
    assert parsed.title == "테스트전자/신규시설투자등/(2026.10.22)신규시설투자등"
    assert (parsed.company_name, parsed.form_name_ko, parsed.amendment) == (
        "테스트전자",
        "신규시설투자등",
        None,
    )
    assert [s.id for s in parsed.outline().sections] == ["body"]


def test_unrendered_members_are_listed(zipper, periodic):
    archive = zipper({"20260101000001.pdf": b"%PDF-1.4 \x00\x01", "other.xml": periodic()})
    parsed = parse_filing("20260101000001", archive)
    assert [(d.key, d.rendered) for d in parsed.documents] == [("main", True), ("member", False)]
    assert parsed.documents[0].member == "other.xml"
    binary = parsed.outline("member")
    assert binary.sections == []
    assert binary.notes == [
        "Member 20260101000001.pdf (11 bytes) is not DART XML or KRX HTML; not rendered."
    ]
    chunk = parsed.read(document="member")
    assert (chunk.content, chunk.total_chars, chunk.next_offset) == ("", 0, None)
    assert chunk.notes[0].startswith("Member 20260101000001.pdf")
    assert parsed.search("x", document="member").hits == []


def test_duplicate_member_keys_get_suffixes(zipper, periodic):
    archive = zipper({"A/X_1.xml": periodic(), "B/X_1.xml": periodic(), "X_1.xml": periodic()})
    parsed = parse_filing("X", archive)
    assert [d.key for d in parsed.documents] == ["main", "1", "1~2"]


def test_archives_without_markup_are_malformed(zipper):
    with pytest.raises(MalformedArchiveError, match="no DART XML or KRX HTML"):
        parse_filing("1", zipper({"a.bin": b"\x00\x01\x02"}))


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("d-0-3-3-0", "D-0-3-3-0"),
        ("S35", "s35"),
        ("consolidated notes", "D-0-3-3-0"),
        ("share-capital", "D-0-1-3-0"),
        ("Borrowings", "s35"),
        ("risk management", "L-0-2-5-L1"),
        ("차입금", "s35"),
        ("1. 회사의 개요", "D-0-1-1-0"),
        ("Overview", "p7.1.1"),
    ],
)
def test_resolve_section(parsed, query, expected):
    assert parsed.resolve_section(query).id == expected


def test_aliases_fall_back_to_headings_only_on_exact_or_prefix_matches(zipper, periodic):
    renamed = periodic().replace('AASSOCNOTE="D-0-3-3-0"', 'AASSOCNOTE="X-NOTES"')
    parsed = parse_filing(FILING, zipper({f"{FILING}.xml": renamed}))
    assert parsed.resolve_section("consolidated_notes").id == "X-NOTES"
    with pytest.raises(SectionNotFoundError):
        parsed.resolve_section("separate_notes")
    assert "consolidated_notes" in ALIAS_NAMES
    assert len(ALIAS_NAMES) == 23


def test_unknown_sections_list_the_closest_entries(parsed):
    with pytest.raises(SectionNotFoundError, match="no-such-thing") as caught:
        parsed.resolve_section("no-such-thing")
    assert len(caught.value.closest) == 5
    assert caught.value.query == "no-such-thing"
    with pytest.raises(SectionNotFoundError, match="Borrowings"):
        parsed.read(section="Borrowingz section")


def test_english_form_name_fallbacks(zipper, dart_doc):
    cover = dart_doc(
        '<COVER><COVER-TITLE ATOC="Y" ENG="Report on Holdings">보고서</COVER-TITLE></COVER>',
        code="00636",
        name="주식등의 대량보유상황보고서",
    )
    first = dart_doc(
        '<SECTION-1><TITLE ATOC="Y" ENG="Overview">개요</TITLE></SECTION-1>',
        code="99999",
        name="기타",
    )
    issue = dart_doc(
        '<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-0-0-0-0">표지</TITLE></SECTION-1>',
        code="11399",
        name="주요사항보고서(기타)",
    )
    names = [
        parse_filing("1", zipper({"1.xml": doc})).form_name_en for doc in (cover, first, issue)
    ]
    assert names == ["Report on Holdings", "Overview", None]


def test_amendment_edge_cases(zipper, dart_doc):
    body = """<CORRECTION><TITLE ATOC="Y" ATOCID="1">정정신고(보고)</TITLE>
<TABLE><TR><TD>최초제출일</TD><TD>미상</TD></TR></TABLE>
<SECTION-2><TITLE ATOC="N">세부</TITLE>
<TABLE><TR><TH>항목</TH><TH>정정 전</TH><TH>정정 후</TH></TR>
<TR><TD></TD><TD>-</TD><TD></TD></TR>
<TR><TD>가</TD><TD>1</TD><TD>2</TD></TR>
<TR><TD></TD><TD></TD><TD>3</TD></TR></TABLE></SECTION-2></CORRECTION>"""
    parsed = parse_filing("1", zipper({"1.xml": dart_doc(body)}))
    amendment = parsed.amendment
    assert amendment is not None
    assert amendment.original_filed == "미상"
    assert [(c.item, c.before, c.after) for c in amendment.changes] == [
        ("", "-", ""),
        ("가", "1", "2"),
        ("", "", "3"),
    ]
    with pytest.raises(SectionNotFoundError):
        parsed.resolve_section("  ")
