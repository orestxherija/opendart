"""Display units and Korean unit statements."""

from __future__ import annotations

import pytest

from opendart_analysis.domain.units import (
    korean_unit_multiplier,
    parse_unit_statement,
    scale_amount,
    unit_label,
)


@pytest.mark.parametrize(
    ("amount", "unit", "expected"),
    [
        (1_234_567_890, "krw", 1_234_567_890),
        (1_234_567_890, "million_krw", 1234.6),
        (1_234_567_890, "billion_krw", 1.2),
        (1_250_000, "million_krw", 1.3),
        (-1_250_000, "million_krw", -1.3),
        (1_249_999, "million_krw", 1.2),
        (0, "million_krw", 0.0),
        (None, "million_krw", None),
        (None, "krw", None),
        (300_000_000_000_000, "billion_krw", 300000.0),
    ],
)
def test_scale_amount(amount, unit, expected):
    assert scale_amount(amount, unit) == expected


def test_scale_amount_types():
    assert isinstance(scale_amount(5, "krw"), int)
    assert isinstance(scale_amount(5, "million_krw"), float)


@pytest.mark.parametrize(
    ("unit", "label"),
    [("krw", "KRW"), ("million_krw", "KRW million"), ("billion_krw", "KRW billion")],
)
def test_unit_label(unit, label):
    assert unit_label(unit) == label


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("원", 1),
        ("천원", 10**3),
        ("만원", 10**4),
        ("십만원", 10**5),
        ("백만원", 10**6),
        ("백만 원", 10**6),
        (" 백 만 원 ", 10**6),
        ("천만원", 10**7),
        ("억원", 10**8),
        ("십억원", 10**9),
        ("백억원", 10**10),
        ("천억원", 10**11),
        ("조원", 10**12),
        ("주", None),
        ("%", None),
        ("USD", None),
        ("천USD", None),
        ("억", None),
        ("만억원", None),
        ("", None),
    ],
)
def test_korean_unit_multiplier(text, expected):
    assert korean_unit_multiplier(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(단위 : 백만원)", (10**6, False)),
        ("(단위: 원)", (1, False)),
        ("단위 : 조원, %", (10**12, True)),
        ("구분(단위 : 백만원, %)", (10**6, True)),
        ("[단위 : 천원]", (10**3, False)),
        ("\uff08단위\uff1a백만원\uff09", (10**6, False)),
        ("(단위 : 주, 원)", (1, False)),
        ("(단위 : %)", (None, True)),
        ("(단위 : USD)", (None, False)),
        ("(단 위 : 억원)", (10**8, False)),
        ("【단위 : 백만원】", (10**6, False)),
        ("단위 백만원 / %", (10**6, True)),
        ("매출액 현황", (None, False)),
        ("", (None, False)),
    ],
)
def test_parse_unit_statement(text, expected):
    assert parse_unit_statement(text) == expected


def test_unit_statement_stops_at_the_closing_bracket():
    assert parse_unit_statement("(단위 : 백만원) 비율(%)") == (10**6, False)
    assert parse_unit_statement("(단위 : 백만원)\n%") == (10**6, False)
