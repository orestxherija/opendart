"""Company-name normalization."""

from __future__ import annotations

import pytest

from opendart_mcp.domain.names import (
    compact_name,
    has_hangul,
    is_hangul,
    name_tokens,
    normalize_name,
    split_names,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SAMSUNG ELECTRONICS CO,.LTD", "samsung electronics"),
        ("Samsung Electronics Co., Ltd.", "samsung electronics"),
        ("SAMSUNG SDI CO.,LTD", "samsung sdi"),
        ("LG ENERGY SOLUTION, LTD.", "lg energy solution"),
        ("HYUNDAI MOTOR CO", "hyundai motor"),
        ("Celltrion, Inc.", "celltrion"),
        ("Kakao Corp.", "kakao"),
        ("NAVER Corporation", "naver"),
        ("SAMSUNG C&T CORPORATION", "samsung c&t"),
        ("SAMSUNG FIRE & MARINE INSURANCE CO.,LTD", "samsung fire & marine insurance"),
        ("POSCO Holdings Inc.", "posco holdings"),
        ("BNK  3 SPECIAL PURPOSE ACQUISITION COMPANY", "bnk 3 special purpose acquisition"),
        ("Acme PLC", "acme"),
        ("Acme Limited", "acme"),
        ("Acme LLC", "acme"),
        ("Acme Incorporated", "acme"),
        ("ACME COLTD", "acme"),
        ("Sewon & Co., Ltd.", "sewon"),
        ("GLOVIL PROCESS CO., LTD\t\t\t", "glovil process"),
        ("Woo Sang A\uff06C", "woo sang a&c"),
        ("CHA Investment Co. \uff0cLtd.", "cha investment"),
    ],
)
def test_english_legal_forms_are_removed(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("삼성전자", "삼성전자"),
        ("(주)유니맥스", "유니맥스"),
        ("㈜유니맥스", "유니맥스"),
        ("\uff08주\uff09신미코스메틱", "신미코스메틱"),
        ("( 주 )유니맥스", "유니맥스"),
        ("두성공업주식회사", "두성공업"),
        ("주식회사 남원사랑발전소", "남원사랑발전소"),
        ("한국에너지 유한회사", "한국에너지"),
        ("한국에너지 유한책임회사", "한국에너지"),
        ("(유)한국에너지", "한국에너지"),
        ("SK하이닉스", "sk하이닉스"),
        ("에스케이ㆍ텔레콤", "에스케이 텔레콤"),
        ("에스케이·텔레콤", "에스케이 텔레콤"),
    ],
)
def test_korean_legal_forms_are_removed(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Samsung Holdings Co., Ltd.", "samsung holdings"),
        ("Mirae Asset Securities", "mirae asset securities"),
        ("Company Holdings", "company holdings"),
        ("Corporation Bank", "corporation bank"),
    ],
)
def test_meaningful_words_are_kept(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Co., Ltd.", "co"),
        ("Inc.", "inc"),
        ("주식회사", "주식회사"),
        ("(주)", "주"),
        ("", ""),
        ("  -- ..  ", ""),
    ],
)
def test_names_made_only_of_legal_forms_keep_a_word(raw, expected):
    assert normalize_name(raw) == expected


def test_punctuation_except_ampersand_separates_words():
    assert normalize_name("E.B.Tech Co.,Ltd.") == "e b tech"
    assert normalize_name("S-OIL CORPORATION") == "s oil"
    assert normalize_name("KT&G Corporation") == "kt&g"
    assert normalize_name("under_score") == "under score"


def test_compact_name_removes_spaces():
    assert compact_name("Kakao Bank Corp.") == "kakaobank"
    assert compact_name("KakaoBank Corp.") == "kakaobank"
    assert compact_name("sk 하이닉스") == compact_name("SK하이닉스")
    assert compact_name("E.B.Tech") == compact_name("EB Tech")


def test_name_tokens_split_normalized_words():
    assert name_tokens("SAMSUNG ELECTRONICS CO,.LTD") == ("samsung", "electronics")
    assert name_tokens("삼성전자") == ("삼성전자",)
    assert name_tokens("") == ()


def test_full_width_and_compatibility_characters_normalize():
    assert normalize_name("\uff33\uff21\uff2d\uff33\uff35\uff2e\uff27") == "samsung"
    assert normalize_name("HYUNDAI MOTOR ㎏") == "hyundai motor kg"


def test_hangul_detection():
    assert is_hangul("가")
    assert is_hangul("힣")
    assert not is_hangul("a")
    assert not is_hangul("ㄱ")  # Compatibility jamo is not a syllable.
    assert has_hangul("SK하이닉스")
    assert not has_hangul("SK hynix")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "SAMSUNG ELECTRONICS CO,.LTD, SK hynix Inc.; 035420",
            ["SAMSUNG ELECTRONICS CO,.LTD", "SK hynix Inc.", "035420"],
        ),
        ("005930, 000660;035420\nNAVER", ["005930", "000660", "035420", "NAVER"]),
        (
            "Celltrion, Inc., LG ENERGY SOLUTION, LTD.",
            ["Celltrion, Inc.", "LG ENERGY SOLUTION, LTD."],
        ),
        (
            "Samsung Electronics Co., Ltd.,Kakao Corp.",
            ["Samsung Electronics Co., Ltd.", "Kakao Corp."],
        ),
        ("VitzroSys., Co. LTD", ["VitzroSys., Co. LTD"]),
        ("Woori Technology, Incorporation", ["Woori Technology, Incorporation"]),
        ("Ocean Stone Corp,., NAVER", ["Ocean Stone Corp,.", "NAVER"]),
        ("ABC (Korea Co.,Ltd.)", ["ABC (Korea Co.,Ltd.)"]),
        ("SAMSUNG SDI CO.;LTD", ["SAMSUNG SDI CO.;LTD"]),  # the separator is kept
        ("Hyundai Motor Company, Kia Corporation", ["Hyundai Motor Company", "Kia Corporation"]),
        ("Coco, Inco", ["Coco", "Inco"]),  # words that only start like legal forms
        (",LTD, NAVER", ["LTD", "NAVER"]),  # nothing before the fragment to join it to
        (" , ;\n", []),
        ("", []),
    ],
)
def test_company_lists_split_without_breaking_official_names(text, expected):
    assert split_names(text) == expected
