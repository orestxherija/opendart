"""Table cleanup and layout: spans, empty rows and columns, headers, units, and forms."""

from __future__ import annotations

from opendart_analysis.documents.tables import expand, form_lines, markdown_grid, view
from opendart_analysis.documents.tree import Cell, Label, Table


def cell(text: str, eng: str | None = None, **flags) -> Cell:
    return Cell(Label(text, eng), **flags)


def head(text: str, eng: str | None = None, **flags) -> Cell:
    return Cell(Label(text, eng), header=True, **flags)


def val(text: str, **flags) -> Cell:
    return Cell(Label(text), value=True, **flags)


def test_expand_repeats_rowspans_and_marks_colspan_copies():
    group = cell("그룹", rowspan=2)
    wide = cell("넓음", colspan=2)
    table = Table(((group, wide), (cell("가"), cell("나")), (cell("세로", rowspan=5),)))
    grid = expand(table)
    assert [[slot.cell.label.ko if slot else None for slot in row] for row in grid] == [
        ["그룹", "넓음", "넓음"],
        ["그룹", "가", "나"],
        ["세로", None, None],
    ]
    assert [slot.lead for slot in grid[0] if slot] == [True, True, False]


def test_grid_view_combines_headers_and_drops_empty_rows_and_columns():
    table = Table(
        (
            (head("구분", rowspan=2), head("당기", "Current", colspan=2), head("", colspan=1)),
            (head("금액", "Amount"), head("비율", "Rate"), head("")),
            (cell("차입금", rowspan=2), cell("1,000"), cell("3.5"), cell("")),
            (cell("200"), cell("2.0"), cell("")),
            (cell(""), cell(""), cell(""), cell("")),
        )
    )
    shown = view(table, "english")
    assert shown.layout == "grid"
    assert shown.header == ["구분", "Current / Amount", "Current / Rate"]
    assert shown.rows == [["차입금", "1,000", "3.5"], ["차입금", "200", "2.0"]]
    assert view(table, "both").header[1] == "Current (당기) / Amount (금액)"


def test_span_copy_columns_and_colspan_copies_in_body():
    table = Table(
        (
            (head("항목"), head("값", colspan=2)),
            (cell("가"), cell("1", colspan=2)),
            (cell("나"), cell("2"), cell("3")),
        )
    )
    shown = view(table, "korean")
    assert shown.header == ["항목", "값", "값"]
    assert shown.rows == [["가", "1", ""], ["나", "2", "3"]]
    merged = Table(((head("항목"), head("값", colspan=3)), (cell("가"), cell("1", colspan=3))))
    assert view(merged, "korean").header == ["항목", "값"]


def test_units_are_extracted_and_unit_only_cells_removed():
    table = Table(
        (
            (cell("(단위 : 백만원)"),),
            (head("구분(단위 : 원, %)"), head("금액")),
            (cell("매출"), cell("100")),
        )
    )
    shown = view(table, "korean")
    assert shown.unit is not None
    assert shown.unit.english == "KRW million"
    assert shown.header == ["구분(단위 : 원, %)", "금액"]
    assert shown.rows == [["매출", "100"]]


def test_free_form_first_row_becomes_header():
    table = Table(
        (
            (cell("구분"), cell("당기"), cell("전기"), cell("전전기")),
            (cell("매출"), cell("10"), cell("9"), cell("8")),
        )
    )
    shown = view(table, "korean")
    assert shown.layout == "grid"
    assert shown.header == ["구분", "당기", "전기", "전전기"]
    assert shown.rows == [["매출", "10", "9", "8"]]


def test_value_marked_rows_render_as_forms():
    table = Table(
        (
            (cell("1. 사채의 종류", colspan=2), cell("회차"), val("43"), cell("종류"), val("사모")),
            (cell("2. 이율", rowspan=2), cell("표면 (%)"), val("1.5", colspan=4)),
            (cell("만기 (%)"), val("4.0"), cell("~"), val("5.0")),
            (cell("3. 기간"), val("2026-01-01"), cell("부터")),
            (cell("4. 비고"),),
            (val("단독 값"),),
        )
    )
    shown = view(table, "korean")
    assert shown.layout == "form"
    assert form_lines(shown.lines) == [
        "- 1. 사채의 종류 / 회차: 43; 종류: 사모",
        "- 2. 이율 / 표면 (%): 1.5",
        "- 2. 이율 / 만기 (%): 4.0 ~ 5.0",
        "- 3. 기간: 2026-01-01 부터",
        "- 4. 비고",
        "- 단독 값",
    ]


def test_header_like_rows_and_long_value_runs_force_a_grid():
    header_row = Table(
        (
            (cell("항목"), cell("정정전"), cell("정정후")),
            (val("가"), val("1"), val("2")),
        )
    )
    assert view(header_row, "korean").layout == "grid"
    run = Table(((cell("연도"), val("2024"), val("2025"), val("2026")),))
    assert view(run, "korean").layout == "grid"


def test_unmarked_layout_tables_with_three_cells_are_forms():
    table = Table(
        (
            (cell("작 성 책 임 자 :"), cell("(직 책) 팀장"), cell("(성 명) 홍길동")),
            (cell("회 사 명\uff1a"), cell("테스트전자")),
            (cell(""), cell("(전 화) 02-000-0000")),
        ),
        bordered=False,
    )
    shown = view(table, "korean")
    assert form_lines(shown.lines) == [
        "- 작 성 책 임 자: (직 책) 팀장 (성 명) 홍길동",
        "- 회 사 명: 테스트전자",
        "- (전 화) 02-000-0000",
    ]
    wide = Table(((cell("가"), cell("나"), cell("다"), cell("라")),))
    assert view(wide, "korean").layout == "grid"


def test_form_labels_drop_colons_in_every_language():
    table = Table(((cell("제출일 :", "Date:"), val("2026-01-01")),))
    assert form_lines(view(table, "both").lines) == ["- Date (제출일): 2026-01-01"]
    multiline = Table(((cell("내용"), val("첫째\n둘째")),))
    assert form_lines(view(multiline, "korean").lines) == ["- 내용: 첫째\n  둘째"]


def test_markdown_grid_escapes_cells():
    head_block, rows = markdown_grid(["a|b", "c"], [["1\n2", "3"]])
    assert head_block == "| a\\|b | c |\n| --- | --- |"
    assert rows == ["| 1<br>2 | 3 |"]
    blank, _ = markdown_grid([], [["x", "y"]])
    assert blank.splitlines()[0] == "|  |  |"


def test_tables_that_clean_to_nothing():
    shown = view(Table(((cell("(단위 : 원)"),),)), "korean")
    assert shown.layout == "form"
    assert shown.lines == []
    assert shown.unit is not None


def test_oversized_grids_are_cut_by_rows(monkeypatch):
    from opendart_analysis.documents import tables

    monkeypatch.setattr(tables, "MAX_GRID_SLOTS", 10)
    table = Table(tuple((cell(f"행{n}"), val(str(n))) for n in range(30)))
    shown = view(table, "korean")
    assert shown.truncated
    assert len(shown.rows) < 30


def test_rowspan_staircases_stay_bounded():
    rows = tuple((cell(f"계단{n}", rowspan=512),) for n in range(2000))
    grid = expand(Table(rows))
    assert len(grid) < 2000
    assert len(grid) * len(grid[0]) <= 200_000 + 200


def test_truncated_tables_say_so(zipper, dart_doc, monkeypatch):
    from opendart_analysis.documents import parse_filing, tables

    monkeypatch.setattr(tables, "MAX_GRID_SLOTS", 10)
    rows = "".join(f"<TR><TD>항목{n}</TD><TD>{n}</TD><TD>{n}</TD></TR>" for n in range(20))
    archive = zipper({"1.xml": dart_doc(f"<TABLE><TBODY>{rows}</TBODY></TABLE>")})
    content = parse_filing("1", archive).read().content
    assert content.endswith("(Table truncated: it is too large to render in full.)")
