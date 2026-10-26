"""Model-facing messages for company references that do not resolve to one company."""

from __future__ import annotations

import re
from datetime import date

import pytest

from opendart_analysis.domain.directory import CorpRecord, Match
from opendart_mcp.services.company_messages import (
    ambiguity_message,
    not_found_message,
)

# Candidates for an ambiguous "Samsung", listed companies first, as the resolver orders them.
SAMSUNG = (
    CorpRecord("00149655", "삼성물산", "SAMSUNG C&T CORPORATION", "028260", date(2026, 3, 23)),
    CorpRecord("00126380", "삼성전자", "SAMSUNG ELECTRONICS CO,.LTD", "005930", date(2025, 12, 1)),
    CorpRecord("00126362", "삼성SDI", "SAMSUNG SDI CO.,LTD", "006400", date(2026, 3, 6)),
    CorpRecord(
        "00877059", "삼성바이오로직스", "SAMSUNG BIOLOGICS CO.,LTD.", "207940", date(2024, 7, 1)
    ),
    CorpRecord(
        "00126256", "삼성생명", "Samsung Life Insurance co., Ltd", "032830", date(2025, 3, 1)
    ),
    CorpRecord("00126229", "삼성물산", "Samsung C&T Corporation", "000830", date(2017, 6, 30)),
    CorpRecord("01182596", "삼성산업개발", "samsung", None, date(2023, 5, 1)),
)


def test_ambiguity_message_lists_candidates_and_the_fix():
    candidates = [Match(record, 1.0, "prefix") for record in SAMSUNG]
    message = ambiguity_message("Samsung", candidates)
    assert message.startswith(
        "Ambiguous company 'Samsung'; candidates: SAMSUNG C&T CORPORATION (삼성물산; corp 00149655"
    )
    assert len(re.findall(r"corp [0-9]{8}", message)) == 5
    assert f"and {len(candidates) - 5} more (call find_company to list them)" in message
    assert message.endswith("Re-call with a stock code or corp code.")


def test_ambiguity_message_without_hidden_candidates():
    match = Match(SAMSUNG[1], 1.0, "exact")
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
