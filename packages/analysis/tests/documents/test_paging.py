"""Paged reads: tiling, table splits with repeated headers, snapping, scopes, and validation."""

from __future__ import annotations

import pytest

from opendart_analysis.documents import MAX_CHARS_CAP, parse_filing
from opendart_analysis.documents.paging import Scope, _Placed, _page_end

FILING = "20260515003117"
HEADER = "Unit: KRW million\n|  | FY 2026 | FY 2025 |\n| --- | --- | --- |"


@pytest.fixture
def parsed(periodic_archive):
    return parse_filing(FILING, periodic_archive)


def pages(parsed, **kwargs):
    chunks, offset = [], 0
    while True:
        chunk = parsed.read(offset=offset, **kwargs)
        chunks.append(chunk)
        if chunk.next_offset is None:
            return chunks
        assert chunk.truncated
        assert chunk.next_offset > chunk.offset
        offset = chunk.next_offset


@pytest.mark.parametrize("size", [120, 333, 1000, 30_000])
def test_pages_tile_the_document(parsed, size):
    chunks = pages(parsed, max_chars=size)
    total = chunks[0].total_chars
    assert [c.offset for c in chunks[1:]] == [c.next_offset for c in chunks[:-1]]
    assert not chunks[-1].truncated
    whole = parsed.read(max_chars=30_000).content
    assert total == len(whole)
    for chunk in chunks:
        expected = whole[chunk.offset : chunk.next_offset or total].strip("\n")
        if any(note.startswith("This page continues a table") for note in chunk.notes):
            header, _, rest = chunk.content.partition("\n| --- ")
            assert header.startswith(("Unit:", "|"))
            assert chunk.content.endswith(expected)
            assert rest
        else:
            assert chunk.content == expected


def test_split_tables_repeat_their_header(parsed):
    chunks = pages(parsed, section="s32", max_chars=400)
    assert len(chunks) > 3
    first, second = chunks[0], chunks[1]
    assert first.notes == ["A table continues on the next page; its header is repeated there."]
    assert second.content.startswith(HEADER + "\n| Line item")
    assert (
        second.notes[0]
        == "This page continues a table from the previous page; its header is repeated."
    )
    (table,) = second.tables
    assert table.first_row > 0
    assert table.rows[0][0] == second.content.splitlines()[3].split(" | ")[0].removeprefix("| ")
    rows = sum(len(chunk.tables[0].rows) for chunk in chunks if chunk.tables)
    assert rows == chunks[0].tables[0].total_rows == 41
    assert all(len(chunk.content) <= 400 + len(HEADER) + 1 for chunk in chunks)


def test_page_end_never_cuts_inside_a_table_header():
    text = "intro line\nUnit: X\n| a |\n| --- |\n| 1 |\n| 2 |\n"
    start = text.index("Unit")
    body = text.index("| 1 |")
    placed = [_Placed(None, start, body, len(text), (body, text.index("| 2 |")))]  # type: ignore[arg-type]
    assert _page_end(text, 0, start + 12, placed=placed) == start
    assert _page_end(text, 0, len(text) + 5, placed=placed) == len(text)
    assert _page_end("x" * 50, 0, 10, placed=[]) == 10


def test_offset_past_the_end(parsed):
    total = parsed.read().total_chars
    chunk = parsed.read(offset=total + 5)
    assert (chunk.content, chunk.next_offset, chunk.truncated, chunk.tables) == (
        "",
        None,
        False,
        [],
    )
    assert chunk.notes == [f"offset {total + 5:,} is past the end ({total:,} characters)."]


def test_page_size_is_capped_and_validated(parsed):
    chunk = parsed.read(max_chars=MAX_CHARS_CAP + 1)
    assert chunk.notes[0] == "max_chars was capped at 30,000."
    with pytest.raises(ValueError, match="offset"):
        parsed.read(offset=-1)
    with pytest.raises(ValueError, match="max_chars"):
        parsed.read(max_chars=0)
    with pytest.raises(ValueError, match="labels"):
        parsed.read(labels="french")


def test_offsets_snap_back_to_their_line_start(parsed):
    section = parsed.section_markdown("D-0-1-1-0")
    line = section.index("당사는")
    chunk = parsed.read(section="D-0-1-1-0", offset=line + 5, max_chars=2000)
    assert chunk.offset == line
    assert chunk.content.startswith("당사는 R&D")
    far = parsed.read(section="D-0-1-1-0", offset=line + 5, max_chars=8)
    assert far.offset == line + 5


def test_alias_scopes_span_several_sections(parsed):
    chunk = parsed.read(section="share_capital", max_chars=30_000)
    capital = parsed.section_markdown("D-0-1-3-0")
    shares = parsed.section_markdown("D-0-1-4-0")
    assert chunk.content == f"{capital}\n\n{shares}"
    assert chunk.total_chars == len(capital) + 2 + len(shares)
    assert chunk.section is not None
    assert chunk.section.id == "D-0-1-3-0"
    assert chunk.notes[0] == "'share_capital' covers sections D-0-1-3-0, D-0-1-4-0."
    assert chunk.notes[1] == "This section only states that the item is omitted or not applicable."
    assert parsed.section_markdown("share_capital") == chunk.content


def test_section_notes_and_whole_document_reads(parsed):
    image = parsed.read(section="TTL_CEO_CERT")
    assert image.notes == ["This section holds only images, which the archive does not include."]
    whole = parsed.read(max_chars=200)
    assert whole.section is None
    assert whole.labels == "english"
    assert parsed.read(section="D-0-1-1-0").notes == []


def test_scope_mapping():
    scope = Scope.of([(10, 15), (0, 5), (16, 20)])
    assert scope.ranges == ((0, 5), (10, 20))
    assert scope.length == 5 + 2 + 10
    full = "abcde-----KLMNOPQRST"
    assert scope.text(full) == "abcde\n\nKLMNOPQRST"
    assert scope.relative(12) == 9
    assert scope.relative(7) is None
    assert scope.absolute(9) == 12
    assert scope.absolute(6) == 10
    assert scope.absolute(99) == 20
    assert Scope.of([]).absolute(3) == 0
