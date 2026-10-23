"""Resolving company references and explaining failures."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest

from opendart_mcp.domain.directory import CorpRecord, Directory, Match
from opendart_mcp.domain.resolver import (
    CANDIDATE_POOL,
    ambiguity_message,
    company_label,
    directory_not_ready_message,
    not_found_message,
    resolve,
)

LOADED_AT = datetime(2026, 10, 22, tzinfo=UTC)


def build(*records: CorpRecord) -> Directory:
    return Directory.build(records, loaded_at=LOADED_AT)


def listed(code: str, name: str, english: str | None, modified: date | None = None) -> CorpRecord:
    return CorpRecord(code, name, english, f"9{code[-5:]}", modified)


def unlisted(code: str, name: str, english: str | None) -> CorpRecord:
    return CorpRecord(code, name, english, None, None)


@pytest.mark.parametrize("text", ["005930", "A005930", "005930.KS", "KOSPI:005930", "00126380"])
def test_codes_select_the_company(directory, text):
    resolution = resolve(directory, text)
    assert resolution.reason == "code"
    assert resolution.record.corp_code == "00126380"
    assert [match.tier for match in resolution.candidates] == ["code"]


@pytest.mark.parametrize("text", ["999999", "12345678", "20250314000123", "Zyxwvut Quorum"])
def test_unknown_codes_and_names_are_not_found(directory, text):
    resolution = resolve(directory, text)
    assert resolution.reason == "not_found"
    assert resolution.record is None
    assert resolution.candidates == ()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Samsung Electronics", "00126380"),
        ("SAMSUNG ELECTRONICS CO., LTD.", "00126380"),
        ("삼성전자", "00126380"),
        ("Celltrion", "00413046"),
        ("셀트리온", "00413046"),
        ("Kakao", "00258801"),
        ("NAVER", "00266961"),
        ("POSCO Holdings", "005490"),
        ("현대코퍼레이션", "00164812"),
    ],
)
def test_exact_names_select_the_single_listed_company(directory, text, code):
    resolution = resolve(directory, text)
    assert resolution.reason == "exact"
    assert code in {resolution.record.corp_code, resolution.record.stock_code}


@pytest.mark.parametrize(
    ("text", "code"), [("Samsung C&T", "00149655"), ("삼성물산", "00149655"), ("SK", "00181712")]
)
def test_duplicate_listed_names_select_a_clearly_newer_record(directory, text, code):
    resolution = resolve(directory, text)
    assert resolution.reason == "exact"
    assert resolution.record.corp_code == code


def test_duplicate_listed_names_modified_close_together_are_ambiguous(directory):
    resolution = resolve(directory, "대한정밀")
    assert resolution.reason == "ambiguous"
    assert [match.record.corp_code for match in resolution.candidates] == ["09000101", "09000102"]


@pytest.mark.parametrize(
    ("newer", "older"),
    [(None, date(2017, 6, 30)), (date(2026, 1, 1), None), (date(2026, 1, 1), date(2024, 1, 2))],
)
def test_recency_needs_known_dates_two_years_apart(newer, older):
    directory = build(
        listed("09000201", "가나", "Gana", newer), listed("09000202", "가나", "Gana Co", older)
    )
    assert resolve(directory, "가나").reason == "ambiguous"


def test_recency_of_exactly_two_years_selects_the_newer_record():
    directory = build(
        listed("09000201", "가나", "Gana", date(2026, 1, 1)),
        listed("09000202", "가나", "Gana Co", date(2024, 1, 1)),
    )
    assert resolve(directory, "Gana").record.corp_code == "09000201"


def test_business_group_names_are_ambiguous(directory):
    resolution = resolve(directory, "Hyundai")
    assert resolution.reason == "ambiguous"
    assert resolution.candidates[0].record.corp_code == "00164812"
    assert all(match.record.listed for match in resolution.candidates)


def test_group_guard_needs_three_other_listed_companies():
    directory = build(
        listed("09000301", "알파", "ALPHA CORPORATION"),
        listed("09000302", "알파모터", "Alpha Motor Co., Ltd."),
        listed("09000303", "알파스틸", "Alpha Steel Co., Ltd."),
    )
    assert resolve(directory, "Alpha").record.corp_code == "09000301"
    grown = build(
        listed("09000301", "알파", "ALPHA CORPORATION"),
        listed("09000302", "알파모터", "Alpha Motor Co., Ltd."),
        listed("09000303", "알파스틸", "Alpha Steel Co., Ltd."),
        listed("09000304", "알파생명", "Alpha Life Co., Ltd."),
        listed("09000305", "알파뱅크", "AlphaBank"),
    )
    assert resolve(grown, "Alpha").reason == "ambiguous"
    assert resolve(grown, "알파").record.corp_code == "09000301"


def test_unlisted_exact_name_yields_to_listed_partial_matches(directory):
    resolution = resolve(directory, "Samsung")
    assert resolution.reason == "ambiguous"
    first_unlisted = next(
        i for i, match in enumerate(resolution.candidates) if not match.record.listed
    )
    assert all(match.record.listed for match in resolution.candidates[:first_unlisted])
    assert not any(match.record.listed for match in resolution.candidates[first_unlisted:])
    assert "01182596" in {match.record.corp_code for match in resolution.candidates}


@pytest.mark.parametrize(
    ("text", "code"), [("Coupang", "01019166"), ("Samsung Electronics Sales", "00252074")]
)
def test_single_unlisted_exact_name_is_selected(directory, text, code):
    resolution = resolve(directory, text)
    assert resolution.reason == "exact"
    assert resolution.record.corp_code == code


def test_several_unlisted_exact_names_are_ambiguous():
    directory = build(
        unlisted("09000401", "베타", "Beta"), unlisted("09000402", "베타", "Beta Co., Ltd.")
    )
    assert resolve(directory, "Beta").reason == "ambiguous"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("LG Energy", "01515323"),
        ("hynix", "00164779"),
        ("Samsung Life", "00126256"),
        ("Samsung Electronics Service", "01345812"),
    ],
)
def test_partial_names_select_a_dominant_company(directory, text, code):
    resolution = resolve(directory, text)
    assert resolution.reason == "dominant"
    assert resolution.record.corp_code == code


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("Samsung Bio", "00877059"),
        ("현대차", "00137997"),
        ("Samsung Elec", "00126380"),
        ("하이닉스", "00164779"),
    ],
)
def test_partial_words_and_rival_listings_stay_ambiguous(directory, text, first):
    resolution = resolve(directory, text)
    assert resolution.reason == "ambiguous"
    assert resolution.candidates[0].record.corp_code == first


def test_too_many_partial_matches_are_ambiguous():
    rows = [listed("09000500", "감마홀딩스", "Gamma Holdings")]
    rows += [unlisted(f"0900051{i}", f"감마{i}", f"Gamma Unit {i}") for i in range(10)]
    directory = build(*rows)
    assert resolve(directory, "Gamma").reason == "ambiguous"
    assert resolve(build(*rows[:10]), "Gamma").record.corp_code == "09000500"


def test_several_unlisted_partial_matches_are_ambiguous():
    directory = build(
        unlisted("09000601", "델타원", "Delta One"), unlisted("09000602", "델타투", "Delta Two")
    )
    assert resolve(directory, "Delta").reason == "ambiguous"


@pytest.mark.parametrize(
    ("text", "code"),
    [("Samsnug Electronics", "00126380"), ("Kakoa", "00258801"), ("Coupang Pya", "01561252")],
)
def test_clear_fuzzy_winners_are_selected(directory, text, code):
    resolution = resolve(directory, text)
    assert resolution.reason == "dominant"
    assert resolution.record.corp_code == code


def test_weak_fuzzy_matches_are_ambiguous(directory):
    resolution = resolve(directory, "셀트리언")
    assert resolution.reason == "ambiguous"
    assert [match.record.corp_code for match in resolution.candidates] == ["00413046", "00421045"]


def test_close_fuzzy_rivals_are_ambiguous():
    directory = build(
        listed("09000701", "오메가테크", "Omega Tech Co., Ltd."),
        listed("09000702", "오메가텍", "Omega Teck Co., Ltd."),
    )
    resolution = resolve(directory, "Omega Tecx")
    assert resolution.reason == "ambiguous"
    assert {match.tier for match in resolution.candidates} == {"fuzzy"}


def test_candidate_pool_is_bounded(directory):
    assert len(resolve(directory, "Samsung").candidates) <= CANDIDATE_POOL


def test_company_label():
    record = CorpRecord(
        "00126380", "삼성전자", "SAMSUNG ELECTRONICS CO,.LTD", "005930", date(2025, 12, 1)
    )
    assert company_label(record) == (
        "SAMSUNG ELECTRONICS CO,.LTD (삼성전자; corp 00126380, stock 005930, modified 2025-12-01)"
    )
    assert (
        company_label(CorpRecord("09000002", "다코", None, None, None))
        == "다코 (corp 09000002, unlisted)"
    )


def test_ambiguity_message_lists_candidates_and_the_fix(directory):
    candidates = resolve(directory, "Samsung").candidates
    message = ambiguity_message("Samsung", candidates)
    assert message.startswith(
        "Ambiguous company 'Samsung'; candidates: SAMSUNG C&T CORPORATION (삼성물산; corp 00149655"
    )
    assert len(re.findall(r"corp [0-9]{8}", message)) == 5
    assert f"and {len(candidates) - 5} more (call find_company to list them)" in message
    assert message.endswith("Re-call with a stock code or corp code.")


def test_ambiguity_message_without_hidden_candidates(directory):
    match = Match(directory.get("00126380"), 1.0, "exact")
    message = ambiguity_message("x", [match], limit=5)
    assert "more" not in message
    assert "modified 2025-12-01" in message


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Acme", "No company matches 'Acme'. Call find_company"),
        ("999999", "No company in the DART directory has stock code 999999."),
        ("A999999", "No company in the DART directory has stock code 999999."),
        ("12345678", "No company in the DART directory has corp code 12345678."),
        ("20250314000123", "20250314000123 is a filing number, not a company."),
    ],
)
def test_not_found_message(text, expected):
    assert not_found_message(text).startswith(expected)


def test_directory_not_ready_message():
    assert "still loading (42 s so far)" in directory_not_ready_message(elapsed_seconds=42.7)
    assert "still loading;" in directory_not_ready_message()
    failed = directory_not_ready_message(error="HTTP 503", elapsed_seconds=1.0)
    assert failed.startswith("The company directory could not be loaded (HTTP 503)")
    assert all("8-digit DART corp code" in text for text in (failed, directory_not_ready_message()))
