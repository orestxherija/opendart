"""Value normalization by field kind, date ranges, yes/no words, and headline formatting."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_analysis.events.values import display, normalize, parse_flag, parse_span, shorten, won


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Y", True),
        ("Yes", True),
        ("Applicable", True),
        ("Present", True),
        ("해당", True),
        ("N", False),
        ("Non-applicable", False),
        ("N/A", False),
        ("Absent", False),
        ("해당사항 없음", False),
        ("-", None),
        (None, None),
        ("maybe", None),
    ],
)
def test_parse_flag(raw, expected):
    assert parse_flag(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026.12.14", (date(2026, 12, 14), date(2026, 12, 14))),
        ("2026.12.14 ~ 2026.12.15", (date(2026, 12, 14), date(2026, 12, 15))),
        (f"2026-12-14{chr(0xFF5E)}2026-12-18", (date(2026, 12, 14), date(2026, 12, 18))),
        ("2026년 11월 10일 ~ 2026년 11월 17일", (date(2026, 11, 10), date(2026, 11, 17))),
        ("2026.12.28 ~ 12.30", (date(2026, 12, 28), date(2026, 12, 30))),
        ("2026.12.28 ~ 01.08", (date(2026, 12, 28), date(2027, 1, 8))),  # into the next year
        ("2027.12.28 ~ 02.29", (date(2027, 12, 28), date(2028, 2, 29))),
        ("2026.12.28 ~ 02.29", None),
        ("2026.12.28 ~ 12.28", (date(2026, 12, 28), date(2026, 12, 28))),
        ("2026.12.28 ~ 13.40", None),
        ("2026.12.28 ~ soon", None),
        ("2026.12.15 ~ 2026.12.14", None),
        ("2026.01.01 ~ 2026.02.01 ~ 2026.03.01", None),
        ("미정", None),
        ("-", None),
        (None, None),
    ],
)
def test_parse_span(raw, expected):
    assert parse_span(raw) == expected


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("amount", "5,000,000,000", 5_000_000_000),
        ("amount", "-29,080,987", -29_080_987),
        ("amount", "-", None),
        ("count", "771,010주", 771_010),
        ("count", "1,000 shrs.", 1000),
        ("per_share", "6,485", 6485),
        ("per_share", "6,485.5원", 6485.5),
        ("number", "12", 12),
        ("percent", "8.52", 8.52),
        ("percent", "16.3%", 16.3),
        ("flag", "Non-applicable", False),
        ("date", "2029.11.12", "2029-11-12"),
        ("date", "2026.12.14 ~ 2026.12.15", "2026-12-14/2026-12-15"),
        ("period", "미정", "미정"),
        ("date", "-", None),
        ("ratio", " 1 :  0.5 ", "1 : 0.5"),
        ("code", "5", "5"),
        ("text", "  흡수합병  ", "흡수합병"),
        ("text", None, None),
    ],
)
def test_normalize_by_kind(kind, raw, expected):
    assert normalize(kind, raw) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1_234_000_000_000, "KRW 1.2tn"),
        (5_000_000_000, "KRW 5.0bn"),
        (350_000_000, "KRW 350.0m"),
        (-29_080_987, "KRW -29.1m"),
        (52_000, "KRW 52,000"),
    ],
)
def test_won(value, expected):
    assert won(value) == expected


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("amount", 5_000_000_000, "KRW 5.0bn"),
        ("per_share", 6485, "KRW 6,485"),
        ("count", 771_010, "771,010"),
        ("number", 1.5, "1.5"),
        ("percent", 8.52, "8.52%"),
        ("percent", 2.0, "2%"),
        ("flag", True, "yes"),
        ("flag", False, "no"),
        ("date", "2026-12-14/2026-12-15", "2026-12-14 to 2026-12-15"),
        ("text", "x" * 70, "x" * 57 + "..."),
        ("ratio", "1 : 0.5", "1 : 0.5"),
        ("text", None, None),
        ("text", "", None),
        ("amount", "not a number", "not a number"),
    ],
)
def test_display(kind, value, expected):
    assert display(kind, value) == expected


def test_shorten_keeps_short_text():
    assert shorten("short", 10) == "short"
    assert shorten("a much longer text", 10) == "a much..."
