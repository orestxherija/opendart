"""The control snapshot as get_ownership shows it: concise listing, detail fields, and notes."""

from __future__ import annotations

from types import SimpleNamespace

from opendart_analysis.capital import ShareClassCounts, ShareCounts
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.ownership import MinorityHolders, control_snapshot
from opendart_mcp.services.control import CONCISE_HOLDERS, snapshot_view

FIELDS = ("stock_knd", "nm", "relate", "trmend_posesn_stock_co", "trmend_posesn_stock_qota_rt")
FIELDS += ("bsis_posesn_stock_co", "bsis_posesn_stock_qota_rt", "rm")
COUNTS = ShareCounts(
    PeriodRef(2025, "FY"),
    "20260310002820",
    None,
    (ShareClassCounts("common", issued=1000, treasury=50, outstanding=950),),
    None,
    None,
)
MINORITY = MinorityHolders(10, 20, 50.0, 100, 10.0, 1000, None)


def row(kind, name, shares, relate="최대주주의 특수관계인"):
    cells = (kind, name, relate, shares, "1.00", shares, "1.00", "장내 매매")
    return SimpleNamespace(**dict(zip(FIELDS, cells, strict=True)))


ROWS = [
    row("보통주", "Parent Co", "300", "최대주주 본인"),
    *(row("보통주", f"Relative {n}", str(20 - n)) for n in range(12)),
    row("우선주", "Parent Co", "5", "최대주주 본인"),
]


def test_concise_snapshots_list_the_largest_holdings_of_the_voting_class():
    snapshot, notes = snapshot_view(control_snapshot(ROWS, COUNTS, MINORITY), detailed=False)
    group = snapshot.largest_shareholder_group
    assert len(group) == CONCISE_HOLDERS
    assert {holder.share_class for holder in group} == {"common"}
    assert (group[0].shares_begin, group[0].note) == (None, None)
    assert snapshot.minority is not None
    assert snapshot.minority.total_shares is None
    assert notes == [
        "free_float_estimate_pct is an estimate: issued common shares minus the controlling group's and treasury shares, over issued shares; other large holders and lock-ups are not excluded.",
        "Showing the 10 largest common-share holdings of the group's 14; response_format='detailed' lists all of them.",
    ]


def test_detailed_snapshots_keep_every_holding_and_field():
    snapshot, notes = snapshot_view(control_snapshot(ROWS, COUNTS, MINORITY), detailed=True)
    group = snapshot.largest_shareholder_group
    assert len(group) == len(ROWS)
    assert group[-1].share_class == "preferred"
    assert (group[0].shares_begin, group[0].note) == (300, "장내 매매")
    assert snapshot.minority is not None
    assert snapshot.minority.total_shares == 1000
    assert len(notes) == 1


def test_snapshots_without_counts_explain_the_missing_estimate():
    snapshot, notes = snapshot_view(control_snapshot(ROWS[:1], None), detailed=False)
    assert snapshot.minority is None
    assert notes == [
        "The free float could not be estimated: the share-count table or the controlling group's total is missing."
    ]
