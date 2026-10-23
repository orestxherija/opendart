"""Debt tables: ladder mapping, issuance parsing, and maturities from the issuance record."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_mcp.services.debt_issuance import (
    company_key,
    is_issue,
    issuance,
    maturities,
    rating,
    redeemed,
)
from opendart_mcp.services.debt_tables import LADDERS, build_ladder, derive, offering

BONDS, SHORT_TERM, PAPER, HYBRID, CONTINGENT = LADDERS
OWN = frozenset({company_key("한빛화학"), company_key("HANBIT CHEMICAL CO., LTD.")})


def row(**fields):
    return SimpleNamespace(**fields)


def balance(kind, **columns):
    return row(remndr_exprtn1="Unredeemed balance", remndr_exprtn2=kind, **columns)


def bond(**overrides):
    fields = {
        "filing_number": "20260325001401",
        "isu_cmpny": "한빛화학",
        "scrits_knd_nm": "Corporate Bonds",
        "isu_mth_nm": "Public offering",
        "isu_de": "2025.02.21",
        "facvalu_totamt": "150,000,000,000",
        "intrt": "3.36 ",
        "evl_grad_instt": "AA-(한국기업평가/NICE신용평가)",
        "mtd": "2027.02.19",
        "repy_at": "미상환",
        "mngt_cmpny": "가나증권, \n 다라증권",
    }
    return row(**(fields | overrides))


TOTAL_ROW = row(isu_cmpny="Total", scrits_knd_nm="-", isu_de="-", facvalu_totamt="9", mtd="-")


def test_ladder_maps_corporate_bond_columns_onto_common_buckets():
    rows = [
        balance(
            "Public offering",
            yy1_below="545,000,000,000",
            yy1_excess_yy2_below="410,000,000,000",
            sm="955,000,000,000",
        ),
        balance(
            "Private placement",
            yy1_below="258,572,000,000",
            yy3_excess_yy4_below="-",
            sm="258,572,000,000",
        ),
        balance(
            "Total",
            yy1_below="803,572,000,000",
            yy1_excess_yy2_below="410,000,000,000",
            yy2_excess_yy3_below="-",
            yy3_excess_yy4_below="40,000,000,000",
            yy4_excess_yy5_below="10,000,000,000",
            yy5_excess_yy10_below="-",
            yy10_excess="-",
            sm="1,263,572,000,000",
        ),
    ]
    entry = build_ladder(BONDS, rows, detailed=False)
    assert entry is not None
    assert entry.instrument == "corporate_bonds"
    assert [(b.maturity_bucket, b.amount) for b in entry.buckets] == [
        ("<=1y", 803_572_000_000),
        ("1-2y", 410_000_000_000),
        ("3-5y", 50_000_000_000),
    ]
    assert (entry.total, entry.public, entry.private) == (
        1_263_572_000_000,
        955_000_000_000,
        258_572_000_000,
    )
    assert entry.filed is None
    assert entry.issuance_limit is None


def test_short_term_bonds_roll_day_buckets_into_a_year_and_keep_limits():
    total = balance(
        "합계",
        de10_below="10,000,000,000",
        de10_excess_de30_below="20,000,000,000",
        de30_excess_de90_below="-",
        de90_excess_de180_below="5,000,000,000",
        de180_excess_yy1_below="-",
        sm="35,000,000,000",
        isu_lmt="100,000,000,000",
        remndr_lmt="65,000,000,000",
    )
    entry = build_ladder(SHORT_TERM, [total], detailed=False)
    assert entry is not None
    assert [(b.maturity_bucket, b.amount) for b in entry.buckets] == [("<=1y", 35_000_000_000)]
    assert (entry.issuance_limit, entry.remaining_limit) == (100_000_000_000, 65_000_000_000)


def test_public_and_private_rows_add_up_when_the_total_row_is_missing():
    rows = [
        balance("공모", yy1_below="100", yy5_excess_yy10_below="50", sm="150"),
        balance("사모", yy1_below="10", sm="10"),
    ]
    entry = build_ladder(BONDS, rows, detailed=False)
    assert entry is not None
    assert [(b.maturity_bucket, b.amount) for b in entry.buckets] == [("<=1y", 110), ("5-10y", 50)]
    assert (entry.total, entry.public, entry.private) == (160, 150, 10)


def test_a_lone_unlabeled_row_is_the_total_and_dash_tables_are_omitted():
    lone = build_ladder(BONDS, [row(remndr_exprtn2="-", yy1_below="7")], detailed=False)
    assert lone is not None
    assert (lone.total, lone.public) == (7, None)
    dashes = [balance(kind, yy1_below="-", sm="-") for kind in ("Public offering", "Total")]
    assert build_ladder(BONDS, dashes, detailed=False) is None
    assert build_ladder(BONDS, [], detailed=False) is None


def test_irregular_buckets_of_hybrids_and_commercial_paper_are_kept():
    hybrid = build_ladder(
        HYBRID,
        [
            balance(
                "Total", yy1_excess_yy5_below="30", yy20_excess_yy30_below="20", yy30_excess="10"
            )
        ],
        detailed=False,
    )
    paper = build_ladder(
        PAPER, [balance("Total", de10_below="5", yy3_excess="3", sm="8")], detailed=False
    )
    contingent = build_ladder(
        CONTINGENT, [balance("Total", yy10_excess_yy20_below="4", yy30_excess="6")], detailed=False
    )
    assert hybrid is not None
    assert paper is not None
    assert contingent is not None
    assert [(b.maturity_bucket, b.amount) for b in hybrid.buckets] == [("1-5y", 30), (">10y", 30)]
    assert hybrid.total == 60
    assert [(b.maturity_bucket, b.amount) for b in paper.buckets] == [("<=1y", 5), (">3y", 3)]
    assert [(b.maturity_bucket, b.amount) for b in contingent.buckets] == [(">10y", 10)]


def test_detailed_ladders_list_every_column_with_catalog_labels():
    rows = [
        balance("Public offering", yy1_below="100", sm="100"),
        balance("Total", yy1_below="100", sm="100"),
    ]
    entry = build_ladder(BONDS, rows, detailed=True)
    assert entry is not None
    assert entry.filed is not None
    assert [bucket.label for bucket in entry.filed][:3] == [
        "1 year or less",
        "1 to 2 years",
        "2 to 3 years",
    ]
    first = entry.filed[0]
    assert (first.public, first.private, first.total) == (100, None, 100)


def test_derived_figures_add_instruments_and_the_share_due_within_a_year():
    bonds = build_ladder(
        BONDS, [balance("Total", yy1_below="25", yy1_excess_yy2_below="50")], detailed=False
    )
    paper = build_ladder(PAPER, [balance("Total", de10_below="25")], detailed=False)
    assert bonds is not None
    assert paper is not None
    derived = derive([bonds, paper])
    assert (derived.total_debt_securities, derived.due_within_1y, derived.due_within_1y_pct) == (
        100,
        50,
        50.0,
    )
    assert derive([]).total_debt_securities is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Public offering", "public"),
        ("Private placement", "private"),
        ("Total", "total"),
        ("합 계", "total"),
        ("공모", "public"),
        ("Unredeemed balance", None),
        (None, None),
    ],
)
def test_offering_types(label, expected):
    assert offering(label) == expected


@pytest.mark.parametrize(
    ("filed", "expected"),
    [
        ("A1(한국기업평가/NICE신용평가)", ("A1", "Korea Ratings, NICE Investors Service")),
        ("AA-(S&P), \nAa2(Moody's)", ("AA-; Aa2", "S&P; Moody's")),
        ("A+(한국신용평가, 서울신용평가)", ("A+", "Korea Investors Service, Seoul Credit Rating")),
        ("BBB+", ("BBB+", None)),
        ("-", (None, None)),
        (None, (None, None)),
    ],
)
def test_ratings_split_into_grades_and_agencies(filed, expected):
    assert rating(filed) == expected


@pytest.mark.parametrize(
    ("filed", "expected"),
    [
        ("상환", "yes"),
        ("미상환", "no"),
        ("일부상환", "partly"),
        ("Redeemed", "yes"),
        ("Unredeemed", "no"),
        ("Partially redeemed", "partly"),
        ("-", None),
    ],
)
def test_redemption_statuses(filed, expected):
    assert redeemed(filed) == expected


def test_company_keys_ignore_corporate_suffixes():
    assert company_key("삼성전자㈜") == company_key("삼성전자") == "삼성전자"
    assert company_key("HANBIT CHEMICAL CO., LTD.") == "hanbitchemical"
    assert company_key(None) == ""


def test_concise_issuance_keeps_open_issues_by_maturity_without_own_name():
    rows = [
        bond(mtd="2028.02.21", isu_de="2025.03.01"),
        bond(repy_at="상환", mtd="2025.06.30"),
        bond(
            isu_cmpny="Hanbit Q Holdings",
            scrits_knd_nm="Hybrid Securities",
            mtd="2055.04.01",
            isu_mth_nm="Private placement",
            evl_grad_instt="-",
        ),
        bond(repy_at="일부상환", mtd="2027.01.05", isu_cmpny="한빛화학㈜"),
        TOTAL_ROW,
    ]
    issues, omitted = issuance(rows, OWN, detailed=False)
    assert omitted == 1
    assert [item.maturity for item in issues] == [
        dt.date(2027, 1, 5),
        dt.date(2028, 2, 21),
        dt.date(2055, 4, 1),
    ]
    first, _, hybrid = issues
    assert (first.redeemed, first.issuer, first.underwriter) == ("partly", None, None)
    assert (first.amount, first.coupon, first.method) == (150_000_000_000, 3.36, "public")
    assert (first.rating, first.rating_agency) == ("AA-", "Korea Ratings, NICE Investors Service")
    assert (hybrid.issuer, hybrid.method, hybrid.rating) == ("Hanbit Q Holdings", "private", None)


def test_detailed_issuance_keeps_redeemed_issues_and_underwriters():
    issues, omitted = issuance([bond(repy_at="상환"), TOTAL_ROW], OWN, detailed=True)
    assert omitted == 0
    (item,) = issues
    assert (item.redeemed, item.issuer, item.underwriter) == (
        "yes",
        "한빛화학",
        "가나증권, 다라증권",
    )


def test_total_and_blank_rows_are_not_issues():
    assert not is_issue(TOTAL_ROW)
    assert not is_issue(row(isu_cmpny="한빛화학", isu_de="-", scrits_knd_nm="-"))
    assert is_issue(bond())


def test_maturities_fall_in_the_window_once_and_skip_redeemed_issues():
    start, until = dt.date(2026, 10, 22), dt.date(2027, 6, 30)
    rows = [
        bond(mtd="2027.02.19"),
        bond(mtd="2027.02.19", filing_number="20260814001234"),
        bond(scrits_knd_nm="Commercial Paper", mtd="2026.11.30", facvalu_totamt="50,000,000,000"),
        bond(mtd="2026.12.01", repy_at="상환"),
        bond(mtd="2027.06.30", repy_at="일부상환", facvalu_totamt="143,490,000,000"),
        bond(mtd="2027.07.01"),
        bond(mtd="2026.10.21"),
        bond(mtd="-"),
        TOTAL_ROW,
    ]
    schedule = maturities(rows, OWN, start=start, until=until)
    assert [(m.date, m.instrument, m.face_value, m.redeemed) for m in schedule] == [
        (dt.date(2026, 11, 30), "Commercial Paper", 50_000_000_000, "no"),
        (dt.date(2027, 2, 19), "Corporate Bonds", 150_000_000_000, "no"),
        (dt.date(2027, 6, 30), "Corporate Bonds", 143_490_000_000, "partly"),
    ]
    assert schedule[1].filing_number == "20260325001401"
    assert schedule[1].coupon == 3.36
