"""Directory lookups and ranked name search."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from opendart_analysis.domain.directory import TIER_ORDER, CorpRecord, Directory, Match

LOADED_AT = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)


def codes(matches: tuple[Match, ...]) -> list[str]:
    return [match.record.corp_code for match in matches]


def test_size_listing_and_load_time(directory, records):
    assert len(directory) == len(records)
    assert directory.listed_count == sum(record.listed for record in records)
    assert directory.loaded_at == LOADED_AT


def test_records_round_trip_through_packed_columns(directory, records):
    for record in records:
        assert directory.get(record.corp_code) == record


def test_build_sorts_and_keeps_the_first_of_repeated_codes():
    first = CorpRecord("00000002", "둘", None, None, None)
    repeated = CorpRecord("00000002", "중복", "Repeat", "000002", date(2025, 1, 1))
    other = CorpRecord("00000001", "하나", "One", None, None)
    directory = Directory.build([first, repeated, other], loaded_at=LOADED_AT)
    assert len(directory) == 2
    assert directory.get("00000002") == first
    assert directory.listed_count == 0


def test_constructor_sorts_like_build():
    later = CorpRecord("00000002", "둘", None, "000002", None)
    earlier = CorpRecord("00000001", "하나", None, None, None)
    directory = Directory([later, earlier], loaded_at=LOADED_AT)
    assert directory.get("00000001") == earlier
    assert directory.get("00000002") == later


def test_repeated_stock_codes_prefer_the_newest_record():
    old = CorpRecord("00000001", "옛회사", None, "123456", date(2017, 6, 30))
    new = CorpRecord("00000002", "새회사", None, "123456", date(2025, 1, 1))
    older = CorpRecord("00000003", "더옛회사", None, "123456", date(2010, 1, 1))
    directory = Directory.build([old, new, older], loaded_at=LOADED_AT)
    assert directory.by_stock_code("123456") == new
    assert directory.listed_count == 3


def test_empty_directory():
    directory = Directory.build([], loaded_at=LOADED_AT)
    assert len(directory) == 0
    assert directory.get("00126380") is None
    assert directory.search("Samsung") == ()


@pytest.mark.parametrize(
    ("code", "found"),
    [
        ("00126380", True),
        (" 00126380 ", True),
        ("99999999", False),
        ("0012638", False),
        ("abc", False),
    ],
)
def test_get_by_corp_code(directory, code, found):
    record = directory.get(code)
    assert (record is not None) == found
    if found:
        assert record.name == "삼성전자"


def test_get_past_the_largest_code(directory):
    assert directory.get("99999999") is None
    assert directory.get("00000000") is None


def test_by_stock_code(directory):
    assert directory.by_stock_code("005930").corp_code == "00126380"
    assert directory.by_stock_code(" 0068y0 ").corp_code == "01933981"
    assert directory.by_stock_code("999999") is None


def test_record_properties(directory):
    samsung = directory.get("00126380")
    assert samsung.listed
    assert samsung.display_name == "SAMSUNG ELECTRONICS CO,.LTD"
    unnamed = directory.get("09000002")
    assert not unnamed.listed
    assert unnamed.english_name is None
    assert unnamed.modified is None
    assert unnamed.display_name == "다코"


def test_exact_matches_either_language_listed_and_newest_first(directory):
    assert codes_of(directory.exact("Samsung Electronics Co., Ltd.")) == ["00126380"]
    assert codes_of(directory.exact("삼성전자")) == ["00126380"]
    assert codes_of(directory.exact("삼성물산")) == ["00149655", "00126229"]
    assert codes_of(directory.exact("CELLTRION")) == ["00413046", "00421045"]
    assert directory.exact("") == ()
    assert directory.exact("Samsung Elec") == ()


def codes_of(records: tuple[CorpRecord, ...]) -> list[str]:
    return [record.corp_code for record in records]


@pytest.mark.parametrize("query", ["005930", "A005930", "005930.KS", "KRX:005930", "00126380"])
def test_code_queries_match_by_code(directory, query):
    (match,) = directory.search(query)
    assert match == Match(directory.get("00126380"), 1.0, "code")


def test_code_queries_never_fall_back_to_names(directory):
    assert directory.search("999999") == ()
    assert directory.search("12345678") == ()
    assert directory.search("20250314000123") == ()


def test_code_queries_respect_the_listing_filter(directory):
    assert directory.search("005930", listed=False) == ()
    assert codes(directory.search("01019166", listed=False)) == ["01019166"]


def test_exact_tier_comes_first(directory):
    matches = directory.search("Samsung Electronics")
    assert matches[0] == Match(directory.get("00126380"), 1.0, "exact")
    assert {match.tier for match in matches[1:]} <= {"prefix", "token", "fuzzy"}


def test_prefix_tier_ranks_listed_then_coverage(directory):
    matches = directory.search("Samsung Elec")
    assert codes(matches)[:4] == ["00126380", "00126371", "00252074", "01345812"]
    assert [match.tier for match in matches[:4]] == ["prefix"] * 4
    assert matches[0].score == pytest.approx(len("samsungelec") / len("samsungelectronics"))


def test_word_tier_matches_later_words(directory):
    matches = directory.search("hynix")
    assert codes(matches)[:2] == ["00164779", "01265516"]
    assert [match.tier for match in matches[:2]] == ["token", "token"]
    assert directory.search("hynix zzzz") == ()


def test_word_tier_matches_words_in_any_order(directory):
    matches = directory.search("Electronics Samsung")
    assert matches[0].record.corp_code == "00126380"
    assert matches[0].tier == "token"


def test_korean_substrings_match_in_the_word_tier(directory):
    matches = directory.search("하이닉스")
    assert codes(matches)[:2] == ["00164779", "01265516"]
    assert {match.tier for match in matches[:2]} == {"token"}
    assert matches[0].score == pytest.approx(4 / len("sk하이닉스"))


def test_fuzzy_tier_finds_misspellings(directory):
    matches = directory.search("Samsnug Electronics")
    assert matches[0].record.corp_code == "00126380"
    assert matches[0].tier == "fuzzy"
    assert 0.75 <= matches[0].score < 1


def test_fuzzy_tier_finds_korean_misspellings(directory):
    matches = directory.search("셀트리언")
    assert codes(matches) == ["00413046", "00421045"]
    assert {match.tier for match in matches} == {"fuzzy"}


def test_fuzzy_tier_finds_unlisted_neighbors(directory):
    matches = directory.search("Coupang Pya")
    assert codes(matches)[0] == "01561252"
    assert matches[0].tier == "fuzzy"


def test_nothing_similar_finds_nothing(directory):
    assert directory.search("Zyxwvut Quorum") == ()


def test_listing_filter(directory):
    listed = directory.search("Samsung", listed=True, limit=50)
    unlisted = directory.search("Samsung", listed=False, limit=50)
    assert listed
    assert unlisted
    assert all(match.record.listed for match in listed)
    assert not any(match.record.listed for match in unlisted)


def test_limit_bounds_results(directory):
    assert len(directory.search("Samsung", limit=2)) == 2
    assert len(directory.search("Samsung Electronics", limit=1)) == 1
    with pytest.raises(ValueError, match="limit must be at least 1"):
        directory.search("Samsung", limit=0)


def test_ties_prefer_the_most_recently_modified(directory):
    matches = directory.search("SK", limit=3)
    assert codes(matches)[:2] == ["00181712", "00144155"]
    assert [match.tier for match in matches[:2]] == ["exact", "exact"]


def test_single_character_queries_only_match_exactly():
    directory = Directory.build(
        [CorpRecord("00000001", "에이", "A", None, None)], loaded_at=LOADED_AT
    )
    assert codes(directory.search("a")) == ["00000001"]
    assert directory.search("b") == ()


@pytest.mark.parametrize("query", ["", "   ", "---", "Co., Ltd."])
def test_blank_or_legal_form_queries(directory, query):
    assert all(match.tier != "code" for match in directory.search(query))


def test_short_words_are_ignored_by_the_word_tier(directory):
    assert directory.search("a b") == ()


def test_a_record_keeps_its_best_prefix_score():
    record = CorpRecord("00000001", "ABCD", "ABC Co., Ltd.", None, None)
    directory = Directory.build([record], loaded_at=LOADED_AT)
    (match,) = directory.search("ab")
    assert match.tier == "prefix"
    assert match.score == pytest.approx(2 / 3)


def test_scores_stay_within_bounds(directory):
    for query in ["Samsung", "삼성", "hynix", "Samsnug", "Kakao", "현대", "Hyundai Motor"]:
        for match in directory.search(query, limit=50):
            assert 0 <= match.score <= 1
            assert match.tier in TIER_ORDER


def test_words_shared_by_both_names_index_the_record_once():
    record = CorpRecord("00000001", "Alpha Beta", "Alpha Beta Gamma Inc.", None, None)
    directory = Directory.build([record], loaded_at=LOADED_AT)
    (match,) = directory.search("beta")
    assert match.tier == "token"
    assert match.score == pytest.approx(4 / len("alphabetagamma"))
