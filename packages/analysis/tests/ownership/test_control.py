"""Control snapshots from largest-shareholder tables: group totals, basis class, free float."""

from __future__ import annotations

import pytest

from opendart_analysis.capital import ShareClassCounts, ShareCounts
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.ownership import MinorityHolders, control_snapshot, free_float, relation
from packages.analysis.tests.capital.records import Row


def holder(
    name, kind="보통주", relate="최대주주의 특수관계인", end=("100", "1.00"), begin=None, rm="-"
):
    begin = begin or end
    return Row(
        nm=name,
        relate=relate,
        stock_knd=kind,
        bsis_posesn_stock_co=begin[0],
        bsis_posesn_stock_qota_rt=begin[1],
        trmend_posesn_stock_co=end[0],
        trmend_posesn_stock_qota_rt=end[1],
        rm=rm,
    )


def counts(issued=1000, treasury=50, kind="common"):
    row = ShareClassCounts(kind, issued=issued, treasury=treasury, outstanding=issued - treasury)
    return ShareCounts(PeriodRef(2025, "FY"), "20260310002820", None, (row,), None, None)


GROUP = (
    holder(
        "Parent Co",
        relate="최대주주 본인",
        end=("300", "30.00"),
        begin=("310", "31.00"),
        rm="장내 매매",
    ),
    holder("Founder", end=("100", "10.00")),
    holder("Founder", kind="우선주", end=("5", "1.00")),
    holder("Affiliate", relate="계열회사", end=("50", "5.00")),
    holder("Total", relate=None, end=("450", "45.00"), begin=("460", "46.00")),
    holder("Total", kind="우선주", relate=None, end=("5", "1.00")),
)


def test_the_snapshot_uses_the_total_row_of_the_voting_class():
    snapshot = control_snapshot(GROUP, counts())
    assert snapshot.share_class == "common"
    assert snapshot.largest_shareholder == "Parent Co"
    assert snapshot.group_members == 3
    assert (snapshot.controlling_shares, snapshot.controlling_pct) == (450, 45.0)
    assert snapshot.controlling_pct_begin == 46.0
    assert (snapshot.shares_issued, snapshot.treasury_shares, snapshot.shares_outstanding) == (
        1000,
        50,
        950,
    )
    assert snapshot.free_float_estimate_pct == 50.0
    assert snapshot.minority is None
    assert [(h.name, h.share_class) for h in snapshot.holders] == [
        ("Parent Co", "common"),
        ("Founder", "common"),
        ("Affiliate", "common"),
        ("Founder", "preferred"),
    ]
    first = snapshot.holders[0]
    assert (first.relation, first.shares, first.pct_begin, first.pct_end) == (
        "largest shareholder",
        300,
        31.0,
        30.0,
    )
    assert (first.shares_begin, first.note) == (310, "장내 매매")


def test_minority_figures_are_carried_as_given():
    minority = MinorityHolders(10, None, None, None, None, 1000, None)
    assert control_snapshot(GROUP, counts(), minority).minority == minority


def test_without_a_total_row_the_group_is_added_up():
    rows = [row for row in GROUP if row.nm != "Total"]
    snapshot = control_snapshot(rows, counts())
    assert snapshot.controlling_shares == 450
    assert snapshot.controlling_pct == 45.0
    assert snapshot.controlling_pct_begin == 46.0


def test_sums_without_percentages_stay_unknown():
    rows = [holder("Parent Co", relate="최대주주 본인", end=("300", "-"), begin=("300", "-"))]
    snapshot = control_snapshot(rows, counts())
    assert (snapshot.controlling_shares, snapshot.controlling_pct) == (300, None)
    assert snapshot.controlling_pct_begin is None


def test_without_share_counts_the_float_is_not_estimated():
    snapshot = control_snapshot(GROUP, None)
    assert snapshot.share_class == "common"
    assert snapshot.shares_issued is None
    assert snapshot.free_float_estimate_pct is None


def test_treasury_stock_listed_in_the_group_is_not_subtracted_twice():
    rows = [*GROUP[:4], holder("자기주식", relate="본인", end=("50", "5.00"))]
    snapshot = control_snapshot(rows, counts())
    assert snapshot.controlling_shares == 500
    assert snapshot.free_float_estimate_pct == 50.0


def test_the_biggest_holding_is_named_when_no_holder_is_filed_as_largest():
    rows = [
        holder("Small", end=("10", "1.00")),
        holder("Big", relate="계열회사", end=("90", "9.00")),
    ]
    snapshot = control_snapshot(rows, counts())
    assert snapshot.largest_shareholder == "Big"


def test_a_group_holding_only_preferred_shares_is_measured_in_them():
    rows = [holder("Fund", kind="우선주", relate=None, end=("40", "4.00"))]
    snapshot = control_snapshot(rows, counts())
    assert snapshot.share_class == "preferred"
    assert snapshot.shares_issued is None
    assert snapshot.largest_shareholder == "Fund"


def test_total_rows_alone_name_no_holder():
    snapshot = control_snapshot(GROUP[4:5], counts())
    assert snapshot.largest_shareholder is None
    assert snapshot.group_members == 0
    assert snapshot.holders == ()
    assert snapshot.controlling_pct == 45.0


def test_blank_names_and_classes_have_defaults():
    snapshot = control_snapshot([holder("-", kind="-", relate="-")], counts())
    assert (snapshot.holders[0].name, snapshot.holders[0].share_class) == ("unnamed", "common")
    assert snapshot.holders[0].relation is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("최대주주 본인", "largest shareholder"),
        ("최대주주의 특수관계인", "related party"),
        ("계열회사 임원", "affiliate officer"),
        ("출연 재단", "foundation"),
        ("친인척", "relative"),
        ("Other relation", "Other relation"),
        ("-", None),
        (None, None),
    ],
)
def test_relations_are_translated(text, expected):
    assert relation(text) == expected


@pytest.mark.parametrize(
    ("issued", "controlling", "treasury", "expected"),
    [
        (1000, 200, 100, 70.0),
        (1000, 200, None, 80.0),
        (1000, 990, 100, 0.0),
        (None, 200, 100, None),
        (0, 0, 0, None),
        (1000, None, 100, None),
        (3, 1, 0, 66.67),
    ],
)
def test_free_float(issued, controlling, treasury, expected):
    assert free_float(issued, controlling, treasury) == expected
