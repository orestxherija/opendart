"""Search: Korean prose, English labels, word fallback, limits, scopes, and follow-up reads."""

from __future__ import annotations

import pytest

from opendart_analysis.documents import parse_filing

FILING = "20260515003117"


@pytest.fixture
def parsed(periodic_archive):
    return parse_filing(FILING, periodic_archive)


@pytest.mark.parametrize("query", ["전환사채", "전환 사채"])
def test_korean_terms_match_prose_with_any_spacing(parsed, query):
    result = parsed.search(query)
    assert result.total_hits == 2
    (hit,) = result.hits
    assert (hit.section_id, hit.section_title_en) == (
        "L-0-2-5-L1",
        "5. Risk management and derivatives transactions",
    )
    assert "전환 사채 발행 계획" in hit.snippet
    assert result.notes == []


def test_english_terms_match_headings_and_labels(parsed):
    heading = parsed.search("borrowings")
    assert [hit.section_id for hit in heading.hits] == ["s35"]
    label = parsed.search("Line item 40")
    assert [hit.section_id for hit in label.hits] == ["s32"]
    assert "| Line item 40 | 40,000 | (4000) |" in label.hits[0].snippet


def test_label_language_changes_what_matches(parsed):
    english = parsed.search("발행할 주식의 총수")
    assert english.notes[0].startswith("No exact match")
    korean = parsed.search("발행할 주식의 총수", labels="korean")
    assert korean.notes == []
    assert [hit.section_id for hit in korean.hits] == ["D-0-1-4-0"]
    assert "| 발행할 주식의 총수 | 500,000,000 | - |" in korean.hits[0].snippet


def test_words_are_searched_when_the_phrase_is_absent(parsed):
    result = parsed.search("the Borrowings of xyzzy")
    assert result.notes[0] == "No exact match for the phrase; showing matches for its words."
    assert [hit.section_id for hit in result.hits] == ["s35"]
    short = parsed.search("of a")
    assert short.notes[0].startswith("No exact match")
    assert short.total_hits > 0


def test_limits_and_totals(parsed):
    result = parsed.search("Line item", limit=3)
    assert len(result.hits) == 3
    assert result.total_hits == 40
    assert result.notes == ["Showing 3 of 40 matches; narrow the query or section."]
    assert len(parsed.search("Line item", limit=500).hits) <= 50
    assert parsed.search("없는 단어").model_dump()["hits"] == []
    with pytest.raises(ValueError, match="search term"):
        parsed.search("   ")
    with pytest.raises(ValueError, match="limit"):
        parsed.search("x", limit=0)


def test_hit_offsets_feed_follow_up_reads(parsed):
    whole = parsed.search("차입금")
    hit = whole.hits[0]
    assert hit.section_id == "s35"
    page = parsed.read(offset=hit.offset, max_chars=400)
    assert "차입금" in page.content
    scoped = parsed.search("차입금", section="s35")
    assert scoped.section == "s35"
    in_section = parsed.read(section="s35", offset=scoped.hits[0].offset, max_chars=400)
    assert "차입금" in in_section.content
    own = parsed.read(section=hit.section_id, offset=hit.section_offset, max_chars=400)
    assert "차입금" in own.content


def test_snippets_start_at_the_matching_line(parsed):
    hit = parsed.search("Notes to the consolidated").hits[0]
    assert hit.snippet.startswith("## 3. Notes to the consolidated financial statements")
    assert hit.section_offset == 0
    assert hit.snippet.endswith("…")


def test_searching_a_multi_section_alias(parsed):
    result = parsed.search("주식", section="share_capital")
    assert result.notes[0] == "'share_capital' covers sections D-0-1-3-0, D-0-1-4-0."
    assert {hit.section_id for hit in result.hits} == {"D-0-1-4-0"}


def test_overlong_queries_are_rejected(parsed):
    with pytest.raises(ValueError, match="1,000 characters"):
        parsed.search("가" * 1001)
