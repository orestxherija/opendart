"""Friendly filing categories."""

from __future__ import annotations

import types
import typing

import pytest

from opendart.models.disclosures import ListRequest
from opendart_mcp.domain.categories import (
    CATEGORY_INFO,
    EVENT_INDEX_CATEGORIES,
    FILING_CATEGORIES,
    category_query,
)


def sdk_values(field: str) -> set[str]:
    """Allowed values of a ListRequest field, read from the generated SDK model."""
    annotation = ListRequest.model_fields[field].annotation
    if isinstance(annotation, types.UnionType):
        annotation = next(arg for arg in typing.get_args(annotation) if arg is not type(None))
    return set(typing.get_args(annotation))


def test_every_category_has_info_in_order():
    assert len(FILING_CATEGORIES) == len(set(FILING_CATEGORIES)) == 30
    assert tuple(CATEGORY_INFO) == FILING_CATEGORIES
    assert all(info.name == name for name, info in CATEGORY_INFO.items())


def test_codes_match_the_sdk_tables():
    groups = sdk_values("disclosure_category")
    subtypes = sdk_values("disclosure_subcategory")
    for info in CATEGORY_INFO.values():
        assert info.group in groups
        assert info.subtype is None or (
            info.subtype in subtypes and info.subtype.startswith(info.group)
        )
        assert info.description.endswith(".")


def test_every_upstream_group_is_covered():
    covered = {info.group for info in CATEGORY_INFO.values() if info.subtype is None}
    assert covered == sdk_values("disclosure_category")


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


def test_event_index_categories():
    assert EVENT_INDEX_CATEGORIES == ("major_issues", "offerings")
    assert {category_query(name)[0] for name in EVENT_INDEX_CATEGORIES} == {"B", "C"}
