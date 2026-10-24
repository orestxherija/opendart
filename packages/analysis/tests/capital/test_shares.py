"""Share counts by class from the share-count table, and the probe for the newest table."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_analysis.capital import (
    ShareClassCounts,
    is_note,
    latest_share_counts,
    parse_share_counts,
    period_share_counts,
    share_class,
)
from opendart_analysis.capital.shares import is_blank
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.extracts import is_total
from opendart_analysis.reports import ResolvedPeriod
from packages.analysis.tests.capital.records import TODAY, Company, Source, share_row

FY2025 = PeriodRef(2025, "FY")
COMMON_VALUES = ("100", "90", "10", "-", "10", "-", "-", "80", "5", "75")
COMMON = share_row("보통주", *COMMON_VALUES)
PREFERRED = share_row("우선주", "50", "20", "-", "-", "-", "-", "-", "20", "2", "18")
TOTAL = share_row("합계", "150", "110", "10", "-", "10", "-", "-", "100", "7", "93")
NOTE = share_row("비고", "-", "-", "-", "-", "자사주소각", "-", "-", "-", "-", "-")
DASHES = share_row("보통주", *["-"] * 10)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("보통주", "common"),
        ("우선주", "preferred"),
        ("전환우선주", "preferred"),
        ("Common Stock", "common"),
        ("Preferred shares", "preferred"),
        (" 종류주식 ", "종류주식"),
        ("-", None),
        (None, None),
    ],
)
def test_share_classes_are_normalized(text, expected):
    assert share_class(text) == expected


@pytest.mark.parametrize("text", ["Total", "합계", "합 계", "소계", "Subtotal", "총계"])
def test_total_labels(text):
    assert is_total(text)
    assert not is_note(text)


@pytest.mark.parametrize("text", ["Note", "비고", "Remarks"])
def test_note_labels(text):
    assert is_note(text)
    assert not is_total(text)


def test_plain_labels_are_neither_totals_nor_notes():
    assert not is_total("보통주")
    assert not is_total(None)
    assert not is_note("삼성물산")


def test_counts_parse_classes_totals_and_the_note_row():
    counts = parse_share_counts([COMMON, PREFERRED, TOTAL, NOTE], FY2025)
    assert counts is not None
    assert counts.filing_number == "20260310002820"
    assert counts.as_of == date(2025, 12, 31)
    assert [c.share_class for c in counts.classes] == ["common", "preferred"]
    assert counts.classes[0] == ShareClassCounts(
        "common",
        authorized=100,
        issued=80,
        treasury=5,
        outstanding=75,
        issued_to_date=90,
        decreased_to_date=10,
        retired_from_profits=10,
    )
    assert counts.total is not None
    assert counts.total.share_class == "total"
    assert (counts.issued, counts.treasury, counts.outstanding) == (100, 7, 93)
    assert counts.primary is counts.classes[0]
    assert counts.note == "retired from profits: 자사주소각"


def test_without_a_total_row_counts_are_added_up_over_classes():
    counts = parse_share_counts([COMMON, PREFERRED], FY2025)
    assert counts is not None
    assert counts.total is None
    assert counts.note is None
    assert (counts.issued, counts.treasury, counts.outstanding) == (100, 7, 93)


def test_the_first_class_is_primary_without_common_shares():
    counts = parse_share_counts([PREFERRED, TOTAL], FY2025)
    assert counts is not None
    assert counts.primary is not None
    assert counts.primary.share_class == "preferred"


def test_a_total_row_alone_has_no_primary_class():
    counts = parse_share_counts([TOTAL], FY2025)
    assert counts is not None
    assert counts.classes == ()
    assert counts.primary is None
    assert counts.issued == 100


def test_a_blank_class_counts_as_common_shares():
    counts = parse_share_counts([share_row("-", *COMMON_VALUES)], FY2025)
    assert counts is not None
    assert counts.classes[0].share_class == "common"


def test_tables_of_dashes_have_no_counts():
    assert parse_share_counts([DASHES, NOTE], FY2025) is None
    assert parse_share_counts([], FY2025) is None


def test_row_helpers():
    assert not is_blank(ShareClassCounts("common", authorized=1), "share_class")
    assert is_blank(ShareClassCounts("common"), "share_class")
    assert not is_blank(ShareClassCounts("common"))


@pytest.mark.anyio
async def test_one_period_is_read_with_its_volatility():
    source = Source({(2025, "11011"): [COMMON, TOTAL]})
    counts = await period_share_counts(Company(), FY2025, fetch_share_counts=source, today=TODAY)
    assert counts is not None
    assert counts.outstanding == 93
    (query, volatility), *_ = source.queries
    assert (query.corp_code, query.fiscal_year, query.report_code) == ("00126380", 2025, "11011")
    assert volatility == "low"
    recent = await period_share_counts(
        Company(), PeriodRef(2026, "Q3"), fetch_share_counts=source, today=TODAY
    )
    assert recent is None
    assert source.queries[-1][1] == "high"


@pytest.mark.anyio
async def test_the_newest_candidate_with_a_table_wins_within_three_probes():
    candidates = (PeriodRef(2026, "Q3"), PeriodRef(2026, "H1"), PeriodRef(2026, "Q1"))
    resolved = ResolvedPeriod((*candidates, FY2025), None, None)
    source = Source({(2026, "11013"): [COMMON]})
    counts = await latest_share_counts(Company(), resolved, fetch_share_counts=source, today=TODAY)
    assert counts is not None
    assert counts.ref == PeriodRef(2026, "Q1")
    assert len(source.queries) == 3
    empty = Source({(2025, "11011"): [COMMON]})
    assert (
        await latest_share_counts(Company(), resolved, fetch_share_counts=empty, today=TODAY)
        is None
    )
    assert len(empty.queries) == 3
