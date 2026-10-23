"""Corp codes, stock codes, and filing numbers."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_mcp.domain.identifiers import (
    Identifier,
    dart_viewer_url,
    filing_date,
    filing_source,
    is_corp_code,
    is_filing_number,
    parse_identifier,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("00126380", Identifier("corp_code", "00126380")),
        (" 00126380 ", Identifier("corp_code", "00126380")),
        ("005930", Identifier("stock_code", "005930")),
        ("A005930", Identifier("stock_code", "005930")),
        ("a005930", Identifier("stock_code", "005930")),
        ("005930.KS", Identifier("stock_code", "005930")),
        ("035720.KQ", Identifier("stock_code", "035720")),
        ("005930.ks", Identifier("stock_code", "005930")),
        ("278990.KN", Identifier("stock_code", "278990")),
        ("005930 KS", Identifier("stock_code", "005930")),
        ("005930 KS Equity", Identifier("stock_code", "005930")),
        ("KRX:005930", Identifier("stock_code", "005930")),
        ("KOSPI:005930", Identifier("stock_code", "005930")),
        ("KOSDAQ: 035720", Identifier("stock_code", "035720")),
        ("konex-278990", Identifier("stock_code", "278990")),
        ("0088M0", Identifier("stock_code", "0088M0")),
        ("0088m0", Identifier("stock_code", "0088M0")),
        ("A0068Y0", Identifier("stock_code", "0068Y0")),
        ("\uff10\uff10\uff15\uff19\uff13\uff10", Identifier("stock_code", "005930")),
        ("20250314000123", Identifier("filing_number", "20250314000123")),
    ],
)
def test_identifiers_are_recognized(text, expected):
    assert parse_identifier(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Samsung Electronics",
        "삼성전자",
        "05930",
        "0059300",
        "123456789",
        "0088MM",
        "008M80",
        "B005930",
        "005930.KX",
        "NYSE:005930",
        "1234567890123",
        "2025031400012345",
    ],
)
def test_other_text_is_not_an_identifier(text):
    assert parse_identifier(text) is None


def test_code_predicates_require_exact_ascii_digits():
    assert is_corp_code("00126380")
    assert not is_corp_code("0012638")
    assert not is_corp_code("\uff10\uff10\uff11\uff12\uff16\uff13\uff18\uff10")
    assert is_filing_number("20250314000123")
    assert not is_filing_number("2025031400012")


def test_viewer_url_uses_the_documented_template():
    assert dart_viewer_url(" 20250314000123 ") == (
        "https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo=20250314000123"
    )


@pytest.mark.parametrize("bad", ["", "2025", "2025031400012x", "https://example.com"])
def test_viewer_url_rejects_non_filing_numbers(bad):
    with pytest.raises(ValueError, match="14-digit filing number"):
        dart_viewer_url(bad)


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("20250314000123", date(2025, 3, 14)),
        ("20240229800001", date(2024, 2, 29)),
        ("20250230000001", None),
        ("20251301000001", None),
        ("2025031400012", None),
        ("abc", None),
    ],
)
def test_filing_date_comes_from_the_first_eight_digits(number, expected):
    assert filing_date(number) == expected


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("20250314000123", "fss"),
        ("20250314800123", "krx_kospi"),
        ("20250314900123", "krx_kosdaq"),
        ("20261022600567", "krx_konex"),
        ("20250314700123", "other"),
        ("not-a-number", "other"),
    ],
)
def test_filing_source_comes_from_the_sequence_prefix(number, expected):
    assert filing_source(number) == expected
