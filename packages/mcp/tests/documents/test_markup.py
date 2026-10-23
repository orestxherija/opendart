"""Lenient parsing of DART XML and KRX HTML into the document tree."""

from __future__ import annotations

import pytest

from opendart_mcp.documents.building import is_bold, span
from opendart_mcp.documents.krx import title_parts
from opendart_mcp.documents.parsing import parse_markup, sniff_format
from opendart_mcp.documents.tree import (
    Image,
    Label,
    Paragraph,
    Section,
    Subheading,
    Table,
    walk_sections,
)


def parse(text: str, document_format: str = "dart_xml"):
    return parse_markup(text.encode(), document_format)


def sections(tree):
    return [(s.id, s.level, s.parent_id, s.kind, s.title.ko) for s in walk_sections(tree.items)]


def blocks(section: Section):
    return [item for item in section.items if not isinstance(item, Section)]


def test_metadata_and_entities_are_safe(dart_doc):
    tree = parse(dart_doc("<P>R&D &amp; &boom; &lt;x&gt; &#44;</P>", code="00636", name="보고서"))
    assert (tree.form_code, tree.form_name_ko) == ("00636", "보고서")
    assert (tree.company_name, tree.corp_code) == ("테스트전자(주)", "00999999")
    paragraph = tree.items[0]
    assert isinstance(paragraph, Paragraph)
    assert paragraph.plain == "R&D & &boom; <x> ,"


def test_container_headings_loose_toc_titles_and_subheadings(dart_doc):
    body = """<COVER><COVER-TITLE ATOC="Y" AASSOCNOTE="COVER" ENG="Annual Report" ATOCID="1">사업보고서</COVER-TITLE></COVER>
<TITLE ATOC="N" ENG="Table of Contents">목  차</TITLE>
<LIBRARY><SECTION-1><TITLE ATOC="Y" ATOCID="3" ENG="I. Overview">I. 개요</TITLE><P>머리말</P>
<SECTION-2><TITLE ATOC="Y" AASSOCNOTE="D-0-3-2-0" ATOCID="9">2. 연결재무제표</TITLE><P>도입</P>
<TITLE ATOC="Y" ATOCID="10">2-1. 재무상태표</TITLE><P>표1</P>
<TITLE ATOC="N" ENG="Note">참고</TITLE>
<TITLE ATOC="Y" ATOCID="11">2-2. 손익계산서</TITLE><P>표2</P>
</SECTION-2><P>꼬리말</P></SECTION-1></LIBRARY>
<SECTION-1><TITLE ATOC="N">무번호</TITLE><SECTION-2><TITLE ATOC="N">하위</TITLE></SECTION-2></SECTION-1>
<TITLE ATOC="Y">최상위 목차</TITLE><P>끝</P>"""
    tree = parse(dart_doc(body))
    assert tree.cover_title_en == "Annual Report"
    assert sections(tree) == [
        ("COVER", 1, None, "cover", "사업보고서"),
        ("s3", 1, None, "section", "I. 개요"),
        ("D-0-3-2-0", 2, "s3", "section", "2. 연결재무제표"),
        ("s10", 3, "D-0-3-2-0", "section", "2-1. 재무상태표"),
        ("s11", 3, "D-0-3-2-0", "section", "2-2. 손익계산서"),
        ("p3", 1, None, "section", "무번호"),
        ("p3.1", 2, "p3", "section", "하위"),
        ("p4", 1, None, "section", "최상위 목차"),
    ]
    overview = walk_sections(tree.items)[1]
    texts = [item.plain if isinstance(item, Paragraph) else item.id for item in overview.items]
    assert texts == ["머리말", "D-0-3-2-0", "꼬리말"]
    first_statement = walk_sections(tree.items)[3]
    assert blocks(first_statement)[-1] == Subheading(Label("참고", "Note"))
    assert not any(isinstance(item, Subheading) for item in tree.items)


def test_section_ids_are_unique_and_uri_safe(dart_doc):
    body = """<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-1 /x">가</TITLE></SECTION-1>
<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-1_x">나</TITLE></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="7">다</TITLE></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="7">라</TITLE></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="x">마</TITLE></SECTION-1>"""
    assert [entry[0] for entry in sections(parse(dart_doc(body)))] == [
        "D-1_x",
        "D-1_x~2",
        "s7",
        "s7~2",
        "p5",
    ]


def test_untitled_containers_are_transparent(dart_doc):
    body = """<SECTION-1><TITLE ATOC="Y" ATOCID="1">상위</TITLE>
<SECTION-2><TITLE ATOC="N"></TITLE><P>제목 없는 내용</P></SECTION-2></SECTION-1>"""
    (section,) = walk_sections(parse(dart_doc(body)).items)
    assert [item.plain for item in blocks(section) if isinstance(item, Paragraph)] == [
        "제목 없는 내용"
    ]


def test_unclosed_tags_and_stray_end_tags(dart_doc):
    body = """<SECTION-1><TITLE ATOC="Y" ATOCID="1">표</TITLE></SPAN>
<TABLE><TBODY><TR><TD>가<TD>나<TR><TD>다<TD>라</TBODY></TABLE>
<P>닫히지 않은 문단</SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="2">다음</TITLE><P>정상</P></SECTION-1>"""
    first, second = walk_sections(parse(dart_doc(body)).items)
    table, paragraph = blocks(first)
    assert isinstance(table, Table)
    assert [[cell.label.ko for cell in row] for row in table.rows] == [["가", "나"], ["다", "라"]]
    assert isinstance(paragraph, Paragraph)
    assert paragraph.plain == "닫히지 않은 문단"
    assert second.title.ko == "다음"


def test_unclosed_title_does_not_swallow_the_document(dart_doc):
    body = """<SECTION-1><TITLE ATOC="Y" ATOCID="1">제목</SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="2">둘째</TITLE><P>본문</P></SECTION-1>"""
    first, second = walk_sections(parse(dart_doc(body)).items)
    assert (first.title.ko, second.title.ko) == ("제목", "둘째")
    assert blocks(second) == [Paragraph(blocks(second)[0].runs)]


def test_nested_tables_flatten_into_their_cell(dart_doc):
    body = """<TABLE><TR><TD>바깥<TABLE><TR><TD>안1</TD><TD>안2</TD></TR><TR><TD>안3</TD></TR></TABLE></TD>
<TD>옆</TD></TR></TABLE>"""
    table = parse(dart_doc(body)).items[0]
    assert isinstance(table, Table)
    assert [cell.label.ko for cell in table.rows[0]] == ["바깥\n안1 안2\n안3", "옆"]


def test_empty_tables_are_dropped(dart_doc):
    assert parse(dart_doc("<TABLE><TR><TD> </TD></TR></TABLE><P>본문</P>")).items == (
        Paragraph(parse(dart_doc("<P>본문</P>")).items[0].runs),
    )


def test_images_with_captions_filenames_and_in_cells(dart_doc):
    body = """<IMAGE><IMG>사진.jpg</IMG><IMG-CAPTION>설명</IMG-CAPTION></IMAGE>
<IMAGE><IMG>이름만.png</IMG></IMAGE><IMG>단독.gif</IMG><IMAGE></IMAGE>
<TABLE><TR><TD>표 <IMAGE><IMG>셀.jpg</IMG></IMAGE></TD></TR></TABLE>"""
    items = parse(dart_doc(body)).items
    assert items[:4] == (Image("설명"), Image("이름만.png"), Image("단독.gif"), Image("image"))
    table = items[4]
    assert isinstance(table, Table)
    assert table.rows[0][0].label.ko == "표 [image not included: 셀.jpg]"


def test_bold_runs_follow_usermark_tokens(dart_doc):
    body = """<P USERMARK="F-14 B">굵은 제목</P>
<P>보통 <SPAN USERMARK="BU">강조</SPAN> <SPAN USERMARK="BC0XD9D9D9">배경</SPAN></P>
<P USERMARK="B">굵게 <SPAN USERMARK="!B">해제</SPAN></P>
<P USERMARK="A-C"><SPAN USERMARK="B"> </SPAN>공백</P>"""
    paragraphs = [item for item in parse(dart_doc(body)).items if isinstance(item, Paragraph)]
    assert [[(run.text, run.bold) for run in p.runs] for p in paragraphs] == [
        [("굵은 제목", True)],
        [("보통 ", False), ("강조 ", True), ("배경", False)],
        [("굵게 ", True), ("해제", False)],
        [("공백", False)],
    ]


@pytest.mark.parametrize(
    ("usermark", "expected"),
    [
        ("B", True),
        ("F-GL11 BU", True),
        ("I", None),
        ("BC0XD9D9D9", None),
        ("!B", False),
        (None, None),
    ],
)
def test_usermark_interpretation(usermark, expected):
    assert is_bold(usermark) is expected


@pytest.mark.parametrize(
    ("value", "expected"), [("3", 3), ("0", 1), ("x", 1), (None, 1), ("9999", 64), (" 2 ", 2)]
)
def test_span_attributes_are_bounded(value, expected):
    assert span(value, 64) == expected


def test_cp949_members_parse(dart_doc):
    tree = parse_markup(dart_doc("<P>한글 본문</P>").encode("cp949"), "dart_xml")
    assert tree.items[0].plain == "한글 본문"
    assert tree.form_name_ko == "분기보고서"


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b'<?xml version="1.0"?><DOCUMENT>', "dart_xml"),
        (b"<html><head>", "krx_html"),
        (b"\xef\xbb\xbf <ROOT>", "dart_xml"),
        (b"%PDF-1.4 binary", None),
        (b"", None),
    ],
)
def test_format_sniffing(head, expected):
    assert sniff_format(head) == expected


def test_krx_pages_drop_hidden_content_and_mark_inputs(krx_adhoc):
    tree = parse(krx_adhoc, "krx_html")
    (body,) = walk_sections(tree.items)
    assert (body.id, body.kind, body.level) == ("body", "body", 1)
    assert tree.title == "테스트전자/신규시설투자등/(2026.10.22)신규시설투자등"
    assert (tree.company_name, tree.form_name_ko) == ("테스트전자", "신규시설투자등")
    heading, table = blocks(body)
    assert isinstance(heading, Paragraph)
    assert heading.runs[0].bold
    assert isinstance(table, Table)
    cells = [(cell.label.ko, cell.value) for cell in table.rows[3]]
    assert cells == [
        ("3. 기타 투자판단과 관련한 중요사항", False),
        ("1. 첫째 줄\n2. 둘째 줄", True),
    ]
    assert table.rows[4][1].label.ko == "[image not included: chart.png]"
    assert "숨김" not in repr(tree)
    assert "document.write" not in repr(tree)


def test_krx_page_without_body_or_title(krx_page):
    tree = parse("<p>본문<br>둘째</p><img alt='도표'>", "krx_html")
    (body,) = walk_sections(tree.items)
    assert body.title.ko == "KRX disclosure"
    assert [type(item).__name__ for item in body.items] == ["Paragraph", "Paragraph", "Image"]
    assert parse(krx_page("제목만", ""), "krx_html").title == "제목만"


def test_krx_title_parts():
    assert title_parts("회사/양식/(2026.01.01)제목") == ("회사", "양식")
    assert title_parts("슬래시 없는 제목") == (None, None)
    assert title_parts(None) == (None, None)


def test_stray_rows_and_cells_outside_tables(dart_doc, krx_page):
    tree = parse(dart_doc("<TR><TD>떠돌이</TD></TR></TABLE><TABLE><TD>행 없음</TD></TABLE>"))
    paragraph, table = tree.items
    assert isinstance(paragraph, Paragraph)
    assert paragraph.plain == "떠돌이"
    assert isinstance(table, Table)
    assert table.rows[0][0].label.ko == "행 없음"
    page = parse(krx_page("제목", "<p>보통 <b>굵게</b> <strong>강조</strong></p>"), "krx_html")
    runs = walk_sections(page.items)[0].items[0].runs
    assert [(run.text, run.bold) for run in runs] == [("보통 ", False), ("굵게 강조", True)]


def test_section_nesting_is_capped(dart_doc):
    depth = 20
    opening = "".join(
        f'<SECTION-1><TITLE ATOC="Y" ATOCID="{n}">제목 {n}</TITLE>' for n in range(depth)
    )
    tree = parse(dart_doc(opening + "<P>깊은 본문</P>" + "</SECTION-1>" * depth))
    found = walk_sections(tree.items)
    assert max(section.level for section in found) == 12
    deepest = found[-1]
    assert [item.label.ko for item in blocks(deepest) if isinstance(item, Subheading)] == [
        f"제목 {n}" for n in range(12, depth)
    ]


def test_element_budget(dart_doc, monkeypatch):
    from opendart_mcp.documents import ArchiveTooLargeError, markup

    monkeypatch.setattr(markup, "MAX_ELEMENTS", 50)
    with pytest.raises(ArchiveTooLargeError, match="elements") as caught:
        parse(dart_doc("<P>x</P>" * 60))
    assert caught.value.measure == "elements"
