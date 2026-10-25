"""Filing categories: upstream codes, disjoint requests, and inference from titles."""

from __future__ import annotations

import pytest

from opendart_analysis.filings import category_codes, disjoint_categories, infer_category


def test_subtypes_covered_by_a_requested_group_are_dropped():
    assert disjoint_categories(()) == (None,)
    assert disjoint_categories(
        ("fair_disclosure", "exchange_disclosures", "annual_report", "annual_report")
    ) == ("exchange_disclosures", "annual_report")


def test_subtypes_are_sent_without_their_group():
    assert category_codes(None) == (None, None)
    assert category_codes("major_issues") == ("B", None)
    assert category_codes("fair_disclosure") == (None, "I002")


@pytest.mark.parametrize(
    ("title", "number", "category"),
    [
        ("Quarterly Report (2026.03)", "20260515002181", "quarterly_report"),
        ("Organization of Investor Relations Event", "20261008800028", "exchange_disclosures"),
        ("Contract for Sales or Supply", "20261022900740", "exchange_disclosures"),
        (
            "Report on significant holdings of stocks, etc. (General)",
            "20261016000505",
            "major_holding_report",
        ),
        (
            "Report on status of specific securities, etc. owned by executives and major shareholders",
            "20261019000318",
            "insider_ownership_report",
        ),
        (
            "Report on trading plan of specific securities, etc. by executive officers and major shareholders",
            "20261013000379",
            "insider_trading_plan",
        ),
        ("[Revision of statements]Audit Report (2025.12)", "20260320000111", "audit_reports"),
        ("Treasury Stock Acquisition Result Report", "20261012000421", None),
    ],
)
def test_categories_are_inferred_from_titles_and_numbers(title, number, category):
    assert infer_category(title, number) == category
