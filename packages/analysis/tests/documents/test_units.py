"""Unit statements: detection, English rendering, and won multipliers."""

from __future__ import annotations

import pytest

from opendart_analysis.documents.units import (
    find_unit_statement,
    is_unit_only,
    translate_units,
    won_multiplier,
    won_unit,
)


@pytest.mark.parametrize(
    ("text", "raw", "english"),
    [
        ("(단위 : 백만원)", "(단위 : 백만원)", "KRW million"),
        ("단위 : 조원, %", "단위 : 조원, %", "KRW trillion, %"),
        ("구분(단위 : 백만원, %)", "(단위 : 백만원, %)", "KRW million, %"),
        ("가. 연구개발실적 [단위 : 건]", "[단위 : 건]", "cases"),
        ("\uff08단위\uff1a억원\uff09", "\uff08단위\uff1a억원\uff09", "KRW 100 million"),
        ("(단위 : 원\uff0c주)", "(단위 : 원\uff0c주)", "KRW, shares"),
        ("(단위: 천원, USD, CNY)", "(단위: 천원, USD, CNY)", "KRW thousand, USD, CNY"),
        ("(단위 : 매, 백만 원)", "(단위 : 매, 백만 원)", "sheets, KRW million"),
    ],
)
def test_unit_statements_are_found_and_translated(text, raw, english):
    statement = find_unit_statement(text)
    assert statement is not None
    assert statement.raw == raw
    assert statement.english == english


@pytest.mark.parametrize(
    "text", ["현금창출단위: 반도체", "보고 단위 없음", "(단위 : )", "", "단위"]
)
def test_non_statements_are_ignored(text):
    assert find_unit_statement(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(단위 : 원)", True),
        ("[단위: 백만원, %]", True),
        ("단위 : 조원, %", True),
        ("구분(단위 : 백만원)", False),
        ("매출액", False),
    ],
)
def test_unit_only_text(text, expected):
    assert is_unit_only(text) is expected


def test_unknown_units_stay_verbatim():
    assert translate_units("두, ㎡ ,%") == "두, m², %"


@pytest.mark.parametrize(
    ("text", "multiplier"),
    [
        ("단위 : 조원, %", 10**12),
        ("(단위 : 억원)", 10**8),
        ("백만원", 10**6),
        ("(단위 : 천원)", 10**3),
        ("(단위 : 주, %)", None),
        ("", None),
    ],
)
def test_won_multipliers(text, multiplier):
    assert won_multiplier(text) == multiplier
    statement = find_unit_statement(text)
    if statement is not None:
        assert statement.multiplier == multiplier


def test_won_unit_names_the_monetary_unit():
    assert won_unit("단위 : 억원, %") == (10**8, "KRW 100 million")
    assert won_unit("%, 십억원") == (10**9, "KRW billion")
    assert won_unit("(단위 : %)") is None
