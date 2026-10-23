"""Golden Markdown rendering of sections, tables, units, captions, images, and label modes."""

from __future__ import annotations

import pytest

from opendart_mcp.documents import parse_filing
from opendart_mcp.documents.parsing import parse_markup
from opendart_mcp.documents.render import render

FILING = "20260515003117"

COVER = """# Quarterly Report [COVER]

(제 28 기)

- Fiscal year: 2026년 01월 01일 From
- Fiscal year: 2026년 03월 31일 To

- 회 사 명: 테스트전자 주식회사
- Occurrence of reasons for relief: N/A"""

OVERVIEW = """## 1. Company overview [D-0-1-1-0]

**가. 회사의 법적ㆍ상업적 명칭**

당사는 R&D 및 M&A로 성장했으며 C&T와 **협력**합니다 & &boom; <끝>

\\# 표시 문단

**Minor heading**"""

SHARES = """## 4. Total number of shares, etc. [D-0-1-4-0]

가. 주식의 총수 현황 [단위 : 주]

Unit: shares
| Classification | Class of shares / Common | Class of shares / Preferred |
| --- | --- | --- |
| Authorized | 500,000,000 | - |
| Issued | 16,708,389 | - |"""

BORROWINGS = """### 2. Borrowings (Consolidated) [s35]

Unit: KRW million, %
| 구분(단위 : 백만원, %) | Current / Amount | Current / Rate | Prior / Amount | Prior / Rate |
| --- | --- | --- | --- | --- |
| 단기\\|차입금 | 1,000 | 3.5 | 800 | 4.0 |
| 단기\\|차입금 | 200 | 2.0 |  |  |"""

STATEMENT = """### 2-1. Consolidated Statement Of FinancialPosition [s32]

- Consolidated Statement Of FinancialPosition
- FY 2026 03/31/2026 Current

Unit: KRW million
|  | FY 2026 | FY 2025 |
| --- | --- | --- |
| Assets |  |  |
| Line item 1 | 1,000 | (100) |"""

CORRECTION = """# Report of Disclosure Revision [CORRECTION]

- 2026년 10월 22일

- 1. Disclosure document to be revised: 주요사항보고서(전환사채권 발행결정)"""

DECISION = """# Decision on Issuance of Convertible Bonds [D-0-1-0-0]

- 1. Type of bonds / Ordinal: 43; Class of shares: 무기명식 사모 전환사채
- 2. Total face value of bonds (KRW): 6,000,000,000
- 3. Interest rate / Coupon rate (%): 1.5
- 3. Interest rate / Yield to maturity (%): 4.0
- 4. Method of interest payment: 분기마다 지급한다.
  [사채의 이율]
- 5. Method of bond issuance: Private placement

[image not included: 약정서.jpg]"""


@pytest.fixture
def parsed(periodic_archive):
    return parse_filing(FILING, periodic_archive)


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("COVER", COVER),
        ("D-0-1-1-0", OVERVIEW),
        ("D-0-1-4-0", SHARES),
        ("s35", BORROWINGS),
        (
            "TTL_CEO_CERT",
            "# 【Confirmation by CEO, etc.】 [TTL_CEO_CERT]\n\n[image not included: 대표이사등의확인ㆍ서명]",
        ),
    ],
)
def test_golden_sections(parsed, section, expected):
    assert parsed.section_markdown(section) == expected


def test_caption_tables_pass_unit_and_caption_to_the_statement(parsed):
    statement = parsed.section_markdown("s32")
    assert statement.startswith(STATEMENT)
    assert "(Unit : KRW million)" not in statement
    chunk = parsed.read(section="s32", max_chars=30_000)
    (table,) = chunk.tables
    assert table.unit == "KRW million"
    assert (
        table.caption == "Consolidated Statement Of FinancialPosition / FY 2026 03/31/2026 Current"
    )
    assert table.header == ["", "FY 2026", "FY 2025"]
    assert table.rows[1] == ["Line item 1", "1,000", "(100)"]
    assert (table.first_row, table.total_rows, table.layout) == (0, 41, "grid")


def test_label_modes(parsed):
    korean = parsed.section_markdown("D-0-1-4-0", labels="korean")
    assert korean.splitlines()[0] == "## 4. 주식의 총수 등 [D-0-1-4-0]"
    assert "| 구 분 | 주식의 종류 / 보통주 | 주식의 종류 / 우선주 |" in korean
    both = parsed.section_markdown("COVER", labels="both")
    assert both.splitlines()[0] == "# Quarterly Report (분 기 보 고 서) [COVER]"
    assert "- Occurrence of reasons for relief (면제사유발생): N/A (해당사항 없음)" in both


def test_amended_filing_renders_the_correction_and_form(amended_archive):
    parsed = parse_filing("20261022000506", amended_archive)
    assert parsed.section_markdown("D-0-1-0-0") == DECISION
    correction = parsed.section_markdown("CORRECTION")
    assert correction.startswith(CORRECTION)
    assert "| Items | Reason for revision | Before revision | After revision |" in correction
    assert (
        "| 9-1. 옵션에 관한 사항 | 인수계약서 수정 | 15일이 경과한 날 | 10영업일이 경과한 날<br>(변경) |"
        in correction
    )
    cover = parsed.section_markdown("D-0-0-0-0")
    assert cover.endswith(
        "- 금융위원회 / 한국거래소 귀중: 2026년 10월 22일\n- 작 성 책 임 자: (직 책) 재무팀장 (성 명) 홍길동"
    )


def test_spans_and_owners(periodic, dart_doc):
    tree = parse_markup(periodic().encode(), "dart_xml")
    rendering = render(tree, "english")
    start, end = rendering.spans["D-0-3-3-0"]
    text = rendering.text[start:end]
    assert text.startswith("## 3. Notes to the consolidated financial statements [D-0-3-3-0]")
    assert text.endswith("| 단기\\|차입금 | 200 | 2.0 |  |  |")
    notes_start, _ = rendering.spans["s34"]
    assert rendering.owner(notes_start) == "s34"
    assert rendering.owner(notes_start - 3) == "D-0-3-3-0"
    assert rendering.owner(0) == "COVER"
    assert rendering.owner(len(rendering.text)) is None
    assert rendering.owner(-1) is None
    table = next(t for t in rendering.tables if t.section_id == "s35")
    lines = [rendering.text[row : rendering.text.index("\n", row)] for row in table.rows[:1]]
    assert lines == ["| 단기\\|차입금 | 1,000 | 3.5 | 800 | 4.0 |"]
    assert table.header.splitlines()[0] == "Unit: KRW million, %"
    loose = render(parse_markup(dart_doc("<P>시작</P>").encode(), "dart_xml"), "english")
    assert (loose.text, loose.spans, loose.owner(0)) == ("시작", {}, None)
