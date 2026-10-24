"""Filing titles and remark letters."""

from __future__ import annotations

import pytest

from opendart_analysis.domain.filings import (
    RESUBMISSION_MARKERS,
    TITLE_MARKERS,
    RemarkFlags,
    amendment_marker,
    clean_title,
    is_amendment,
    parse_remarks,
)


def test_clean_title_collapses_padding_and_keeps_korean_suffixes():
    title = "Corporate Value-up Plan (Voluntary Disclosure)   (PBR 개선 계획 제출 기업)  "
    assert (
        clean_title(title)
        == "Corporate Value-up Plan (Voluntary Disclosure) (PBR 개선 계획 제출 기업)"
    )
    assert clean_title("\tAnnual  Report\n(2025.12)") == "Annual Report (2025.12)"


@pytest.mark.parametrize(
    ("title", "marker"),
    [
        ("[Revision of statements] Annual Report (2025.12)", "Revision of statements"),
        ("[Corrected attachment]Annual Report (2025.12)", "Corrected attachment"),
        ("[Added attachment] Securities Report", "Added attachment"),
        ("[Modified registration] Asset Securitization Plan", "Modified registration"),
        ("[Decision to extend] Trust Contract", "Decision to extend"),
        (
            "[Conditions for issuance finalized] Securities Report",
            "Conditions for issuance finalized",
        ),
        ("[Correction order imposed] Securities Report", "Correction order imposed"),
        (
            "[Requested submission of correction] Securities Report",
            "Requested submission of correction",
        ),
        ("  [REVISION  OF STATEMENTS]  Annual Report (2025.12)", "Revision of statements"),
        ("[기재정정]사업보고서 (2025.12)", "Revision of statements"),
        ("[기재 정정] 사업보고서 (2025.12)", "Revision of statements"),
        ("[첨부정정]사업보고서", "Corrected attachment"),
        ("[첨부추가]증권신고서", "Added attachment"),
        ("[변경등록]자산유동화계획", "Modified registration"),
        ("[연장결정]신탁계약", "Decision to extend"),
        ("[발행조건확정]증권신고서", "Conditions for issuance finalized"),
        ("[정정명령부과]증권신고서", "Correction order imposed"),
        ("[정정제출요구]증권신고서", "Requested submission of correction"),
        ("[Correction] Single Sales or Supply Contract", "Correction"),
        ("[Amended] Fair Disclosure", "Amended"),
        ("[정정] 단일판매ㆍ공급계약체결", "정정"),
    ],
)
def test_amendment_markers(title, marker):
    assert amendment_marker(title) == marker


@pytest.mark.parametrize(
    "title",
    [
        "Annual Report (2025.12)",
        "[Fair Disclosure] Preliminary Earnings",
        "Report [Revision of statements]",
        "",
        "[unclosed",
    ],
)
def test_titles_without_amendment_markers(title):
    assert amendment_marker(title) is None


def test_documented_markers_map_to_english_names():
    assert set(TITLE_MARKERS.values()) == RESUBMISSION_MARKERS | {
        "Correction order imposed",
        "Requested submission of correction",
    }


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[Revision of statements] Annual Report (2025.12)", True),
        ("[기재정정]사업보고서 (2025.12)", True),
        ("[Correction] Supply Contract", True),
        ("[Correction order imposed] Securities Report", False),
        ("[Requested submission of correction] Securities Report", False),
        ("[Fair Disclosure] Preliminary Earnings", False),
        ("Annual Report (2025.12)", False),
    ],
)
def test_is_amendment(title, expected):
    assert is_amendment(title) is expected


@pytest.mark.parametrize(
    ("rm", "expected"),
    [
        (
            None,
            RemarkFlags(
                None,
                bond_listed=False,
                fair_trade=False,
                consolidated=False,
                corrected_later=False,
                withdrawn=False,
            ),
        ),
        (
            "",
            RemarkFlags(
                None,
                bond_listed=False,
                fair_trade=False,
                consolidated=False,
                corrected_later=False,
                withdrawn=False,
            ),
        ),
        (
            "S",
            RemarkFlags(
                "KOSPI",
                bond_listed=False,
                fair_trade=False,
                consolidated=False,
                corrected_later=False,
                withdrawn=False,
            ),
        ),
        (
            "KC",
            RemarkFlags(
                "KOSDAQ",
                bond_listed=False,
                fair_trade=False,
                consolidated=True,
                corrected_later=False,
                withdrawn=False,
            ),
        ),
        (
            "nu",
            RemarkFlags(
                "KONEX",
                bond_listed=False,
                fair_trade=False,
                consolidated=False,
                corrected_later=True,
                withdrawn=False,
            ),
        ),
        (
            "BFW",
            RemarkFlags(
                None,
                bond_listed=True,
                fair_trade=True,
                consolidated=False,
                corrected_later=False,
                withdrawn=True,
            ),
        ),
        (
            "유연",
            RemarkFlags(
                "KOSPI",
                bond_listed=False,
                fair_trade=False,
                consolidated=True,
                corrected_later=False,
                withdrawn=False,
            ),
        ),
        (
            "코정",
            RemarkFlags(
                "KOSDAQ",
                bond_listed=False,
                fair_trade=False,
                consolidated=False,
                corrected_later=True,
                withdrawn=False,
            ),
        ),
        (
            "넥채공철",
            RemarkFlags(
                "KONEX",
                bond_listed=True,
                fair_trade=True,
                consolidated=False,
                corrected_later=False,
                withdrawn=True,
            ),
        ),
        (
            "XZ?",
            RemarkFlags(
                None,
                bond_listed=False,
                fair_trade=False,
                consolidated=False,
                corrected_later=False,
                withdrawn=False,
            ),
        ),
    ],
)
def test_parse_remarks(rm, expected):
    assert parse_remarks(rm) == expected
