"""Dividend rows: classification by label, units, share classes, and merging across reports."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opendart_analysis.dividends import basis, measure, merge, share_class, unit, value
from opendart_analysis.domain.periods import PeriodRef


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Par value per share (KRW)", "par_value"),
        ("(Consolidated) profit (KRW million)", "net_income"),
        ("(Non-consolidated) net profit during the term (KRW million)", "net_income"),
        ("(Consolidated) Net profit per share (KRW)", "eps"),
        ("Total cash dividends (KRW million)", "cash_dividends"),
        ("Total share dividends (KRW million)", "stock_dividends"),
        ("(Consolidated) cash dividend payout ratio (%)", "payout_ratio"),
        ("Cash dividend rate of return (%)", "cash_yield"),
        ("Stock dividend rate of return (%)", "stock_yield"),
        ("Cash dividend per share (KRW)", "cash_dps"),
        ("Stock dividend per share (share)", "stock_dps"),
        ("주당액면가액(원)", "par_value"),
        ("(연결)당기순이익(백만원)", "net_income"),
        ("(연결)주당순이익(원)", "eps"),
        ("현금배당금총액(백만원)", "cash_dividends"),
        ("(연결)현금배당성향(%)", "payout_ratio"),
        ("주식배당수익률(%)", "stock_yield"),
        ("주당 현금배당금(원)", "cash_dps"),
        ("주당 주식배당(주)", "stock_dps"),
        ("Interim dividend record date", "other"),
    ],
)
def test_rows_are_classified_by_label(label, expected):
    assert measure(label) == expected


@pytest.mark.parametrize(
    ("label", "kind", "expected"),
    [
        ("Total cash dividends (KRW million)", "cash_dividends", ("KRW", 1_000_000)),
        ("Total cash dividends (KRW)", "cash_dividends", ("KRW", 1)),
        ("현금배당금총액(천원)", "cash_dividends", ("KRW", 1_000)),
        ("Cash dividend per share (KRW)", "cash_dps", ("KRW/share", 1)),
        ("Cash dividend rate of return (%)", "cash_yield", ("%", 1)),
        ("Stock dividend per share (share)", "stock_dps", ("shares/share", 1)),
        ("(Consolidated) profit", "net_income", ("KRW", 1_000_000)),
        ("Something (units unknown)", "other", ("KRW", 1)),
    ],
)
def test_units_come_from_the_label_or_the_standard_table(label, kind, expected):
    assert unit(label, kind) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("(Consolidated) profit (KRW million)", "consolidated"),
        ("(Non-consolidated) net profit during the term (KRW million)", "separate"),
        ("(별도)당기순이익(백만원)", "separate"),
        ("(연결)주당순이익(원)", "consolidated"),
        ("Cash dividend per share (KRW)", None),
    ],
)
def test_earnings_basis(label, expected):
    assert basis(label) == expected


@pytest.mark.parametrize(
    ("filed", "expected"),
    [
        ("보통주", "common"),
        ("우선주", "preferred"),
        ("Common stock", "common"),
        ("-", None),
        ("1우선주", "1우선주"),
    ],
)
def test_share_classes(filed, expected):
    assert share_class(filed) == expected


def test_values_convert_to_the_row_unit():
    assert value("11,107,906", "KRW", 1_000_000) == 11_107_906_000_000
    assert value("1,668", "KRW/share", 1) == 1668
    assert value("25.10", "%", 1) == 25.1
    assert value("0.05", "shares/share", 1) == 0.05
    assert value("-", "KRW", 1) is None


def record(label, stock, current, prior, older):
    return SimpleNamespace(
        filing_number="20260310002820",
        se=label,
        stock_knd=stock,
        thstrm=current,
        frmtrm=prior,
        lwfr=older,
    )


def test_merging_reports_prefers_newer_values_and_keeps_requested_years():
    newest = (
        PeriodRef(2025, "FY"),
        [
            record("Cash dividend per share (KRW)", "보통주", "1,668", "1,446", "1,444"),
            record("Cash dividend per share (KRW)", "우선주", "1,669", "1,447", "1,445"),
            record("Mystery row", "-", "1", "2", "3"),
        ],
    )
    older = (
        PeriodRef(2023, "FY"),
        [record("Cash dividend per share (KRW)", "보통주", "9,999", "1,416", "1,416")],
    )
    rows = merge([newest, older], range(2022, 2026))
    common, preferred, mystery = rows
    assert (common.measure, common.share_class, common.unit) == ("cash_dps", "common", "KRW/share")
    assert common.values == {2025: 1668, 2024: 1446, 2023: 1444, 2022: 1416}
    assert list(common.values) == [2025, 2024, 2023, 2022]
    assert common.label == "Cash dividend per share (KRW)"
    assert preferred.values == {2025: 1669, 2024: 1447, 2023: 1445}
    assert (mystery.measure, mystery.label) == ("other", "Mystery row")
    assert list(mystery.values) == [2025, 2024, 2023]


def test_rows_follow_the_measure_order_and_keep_empty_rows():
    report = (
        PeriodRef(2025, "FY"),
        [
            record("Par value per share (KRW)", "-", "100", "100", "100"),
            record("Mystery row", "-", "1", "-", "-"),
            record("Total share dividends (KRW million)", "-", "-", "-", "-"),
            record("Cash dividend per share (KRW)", "보통주", "1,668", "-", "-"),
            record("Other mystery", "-", "2", "-", "-"),
        ],
    )
    rows = merge([report], range(2025, 2026))
    assert [(row.measure, row.label) for row in rows] == [
        ("cash_dps", "Cash dividend per share (KRW)"),
        ("stock_dividends", "Total share dividends (KRW million)"),
        ("par_value", "Par value per share (KRW)"),
        ("other", "Mystery row"),
        ("other", "Other mystery"),
    ]
    assert rows[1].values == {}
    assert (rows[1].unit, rows[2].values) == ("KRW", {2025: 100})
