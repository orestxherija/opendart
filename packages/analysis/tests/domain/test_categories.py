"""Friendly filing categories."""

from __future__ import annotations

import pytest

from opendart_analysis.domain.categories import (
    CATEGORY_INFO,
    FILING_CATEGORIES,
    category_query,
)


def test_every_category_has_info_in_order():
    assert len(FILING_CATEGORIES) == len(set(FILING_CATEGORIES)) == 30
    assert tuple(CATEGORY_INFO) == FILING_CATEGORIES
    assert all(info.name == name for name, info in CATEGORY_INFO.items())


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("annual_report", ("A", "A001")),
        ("quarterly_report", ("A", "A003")),
        ("major_issues", ("B", None)),
        ("major_holding_report", ("D", "D001")),
        ("insider_ownership_report", ("D", "D002")),
        ("treasury_stock", ("E", "E001")),
        ("fair_disclosure", ("I", "I002")),
        ("fair_trade_commission", ("J", None)),
    ],
)
def test_category_query(category, expected):
    assert category_query(category) == expected


def test_unknown_categories_are_rejected():
    with pytest.raises(
        ValueError, match="Unknown filing category 'press_releases'; use one of: periodic_reports"
    ):
        category_query("press_releases")
