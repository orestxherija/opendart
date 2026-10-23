"""Parsing OpenDART's string fields."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from opendart_mcp.domain.normalize import (
    clean_text,
    market_from_corp_cls,
    parse_amount,
    parse_date,
    parse_decimal,
    parse_percent,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234", 1234),
        (" 1,234,567 ", 1234567),
        ("1234567", 1234567),
        ("0", 0),
        ("-0", 0),
        ("-1,234", -1234),
        ("\u22121,234", -1234),
        ("△1,234", -1234),
        ("△ 1,234", -1234),
        ("(1,234)", -1234),
        ("( 1,234 )", -1234),
        ("+1,234", 1234),
        ("1,234.00", 1234),
        ("\uff11\uff0c\uff12\uff13\uff14", 1234),
        ("123456789012345678901234567890", 123456789012345678901234567890),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        " ",
        "-",
        "\u2212",
        "()",
        "N/A",
        "1,23",
        "12,34,567",
        "1,234.5",
        "1e9",
        "NaN",
        "Infinity",
        "--5",
        "(-5)",
        "5-",
        "▲100",
        "1 234",
        "1" * 65,
        "1,234원",
    ],
)
def test_parse_amount_rejects_junk(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234.5", Decimal("1234.5")),
        ("-0.25", Decimal("-0.25")),
        (".5", Decimal("0.5")),
        ("(3.75)", Decimal("-3.75")),
        ("12", Decimal(12)),
    ],
)
def test_parse_decimal(text, expected):
    assert parse_decimal(text) == expected


@pytest.mark.parametrize("text", [None, "-", "1.2.3", "abc", "1,2"])
def test_parse_decimal_rejects_junk(text):
    assert parse_decimal(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.5", 12.5),
        ("12.5%", 12.5),
        (" -3.2 % ", -3.2),
        ("(3.2)", -3.2),
        ("△3.2%p", -3.2),
        ("100", 100.0),
        ("0.00", 0.0),
    ],
)
def test_parse_percent(text, expected):
    assert parse_percent(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [None, "", "-", "%", "abc%", "12.5%%"])
def test_parse_percent_rejects_junk(text):
    assert parse_percent(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20250131", date(2025, 1, 31)),
        ("2025.01.31", date(2025, 1, 31)),
        ("2025-01-31", date(2025, 1, 31)),
        ("2025/01/31", date(2025, 1, 31)),
        ("2025년 01월 31일", date(2025, 1, 31)),
        ("2025년 1월 5일", date(2025, 1, 5)),
        ("2025. 1. 5.", date(2025, 1, 5)),
        (" 2024-02-29 ", date(2024, 2, 29)),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    "text",
    [None, "", "-", "2025-02-30", "20251301", "2025", "2025-01", "January 5, 2025", "2025년 1월"],
)
def test_parse_date_rejects_junk(text):
    assert parse_date(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("-", None),
        (" - ", None),
        ("\u2014", None),
        ("\uff0d", None),
        ("Samsung   Electronics\t Co.", "Samsung Electronics Co."),
        (
            "Corporate Value-up Plan   (PBR 개선 계획 제출 기업)",
            "Corporate Value-up Plan (PBR 개선 계획 제출 기업)",
        ),
        ("--", "--"),
    ],
)
def test_clean_text(text, expected):
    assert clean_text(text) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("Y", "KOSPI"),
        ("K", "KOSDAQ"),
        ("N", "KONEX"),
        ("E", "OTHER"),
        (" y ", "KOSPI"),
        ("X", None),
        ("", None),
        (None, None),
    ],
)
def test_market_from_corp_cls(code, expected):
    assert market_from_corp_cls(code) == expected
