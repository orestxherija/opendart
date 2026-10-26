"""Board, executives, employees, and pay from synthetic periodic-report rows."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.governance import (
    PayTables,
    board,
    born,
    bullets,
    compensation,
    employees,
    executives,
    full_time,
    gender,
    headline,
    newest,
    people,
    role,
)


def row(**fields):
    return SimpleNamespace(**fields)


def test_board_reads_the_first_filled_row():
    rows = [
        row(drctr_co="-", otcmp_drctr_co="-", apnt="-", rlsofc="-", mdstrm_resig="-"),
        row(drctr_co="9", otcmp_drctr_co="6", apnt="2", rlsofc="0", mdstrm_resig="1"),
    ]
    facts = board(rows)
    assert facts is not None
    assert (facts.directors, facts.outside_directors, facts.outside_director_pct) == (9, 6, 66.7)
    assert (facts.outside_appointed, facts.outside_dismissed, facts.outside_resigned_early) == (
        2,
        0,
        1,
    )
    assert board(rows[:1]) is None
    no_count = board([row(drctr_co="-", otcmp_drctr_co="3")])
    assert no_count is not None
    assert no_count.outside_director_pct is None


@pytest.mark.parametrize(
    ("filed", "expected"),
    [
        ("Executive Directors", "executive_director"),
        ("Outside Director", "outside_director"),
        ("Non-executive Director", "non_executive_director"),
        ("Unregistered executive", "unregistered"),
        ("미등기", "unregistered"),
        ("사외이사", "outside_director"),
        ("기타비상무이사", "non_executive_director"),
        ("감사", "auditor"),
        ("사내이사", "executive_director"),
        ("고문", None),
        (None, None),
    ],
)
def test_roles(filed, expected):
    assert role(filed) == expected


@pytest.mark.parametrize(
    ("filed", "expected"),
    [("Full-time", True), ("Part-time", False), ("상근", True), ("비상근", False), ("-", None)],
)
def test_full_time(filed, expected):
    assert full_time(filed) is expected


def test_small_formatters():
    assert bullets("ㆍ이사회 의장ㆍ감사위원회\n   위원장") == "이사회 의장; 감사위원회 위원장"
    assert bullets("ㆍ") is None
    assert bullets("-") is None
    assert born("1960.12") == "1960-12"
    assert born("1960.13") is None
    assert born(None) is None
    assert gender("Female") == "female"
    assert gender("남") == "male"
    assert gender("성별합계") is None
    assert gender("기타") == "기타"


def executive(name, filed_role, **fields):
    base = {
        "nm": name,
        "sexdstn": "Male",
        "birth_ym": "1965.02",
        "ofcps": "이사",
        "rgist_exctv_at": filed_role,
        "fte_at": "Part-time",
        "chrg_job": "ㆍ감사위원회 위원ㆍ보상위원회 위원",
        "main_career": "ㆍ가나대 교수\nㆍ다라 위원장",
        "mxmm_shrholdr_relate": "계열회사 임원",
        "hffc_pd": "22개월",
        "tenure_end_on": "2027.03.19",
    }
    return row(**(base | fields))


def test_executives_keep_every_named_person_with_details():
    rows = [
        executive("갑", "Executive Directors", fte_at="Full-time", ofcps="대표이사"),
        executive("을", "Outside Director"),
        executive("병", "Unregistered executive", tenure_end_on="-"),
        executive("-", "Outside Director"),
    ]
    first, second, third = executives(rows)
    assert (first.name, first.position, first.role, first.full_time) == (
        "갑",
        "대표이사",
        "executive_director",
        True,
    )
    assert second.responsibilities == "감사위원회 위원; 보상위원회 위원"
    assert second.term_ends == dt.date(2027, 3, 19)
    assert (second.born, second.gender, second.career) == (
        "1965-02",
        "male",
        "가나대 교수; 다라 위원장",
    )
    assert (second.tenure, second.role_as_filed) == ("22개월", "Outside Director")
    assert (third.role, third.term_ends) == ("unregistered", None)


def staff(division, sex, total, **fields):
    base = {
        "fo_bbm": division,
        "sexdstn": sex,
        "rgllbr_co": "-",
        "cnttk_co": "-",
        "sm": total,
        "avrg_cnwk_sdytrn": "      10.0",
        "fyer_salary_totamt": "-",
        "jan_salary_am": "-",
    }
    return row(**(base | fields))


def test_employees_add_gender_subtotals():
    rows = [
        staff("DX", "Male", "300", rgllbr_co="290", cnttk_co="10"),
        staff("DX", "Female", "100", rgllbr_co="98", cnttk_co="2"),
        staff(
            "성별합계",
            "Male",
            "300",
            cnttk_co="10",
            avrg_cnwk_sdytrn="14.0",
            fyer_salary_totamt="30,000,000,000",
            jan_salary_am="100,000,000",
        ),
        staff(
            "성별합계",
            "Female",
            "100",
            cnttk_co="2",
            avrg_cnwk_sdytrn="10.0",
            fyer_salary_totamt="8,000,000,000",
            jan_salary_am="80,000,000",
        ),
    ]
    facts = employees(rows)
    assert facts is not None
    assert (facts.total, facts.fixed_term, facts.total_salary) == (400, 12, 38_000_000_000)
    assert facts.average_salary == 95_000_000
    assert facts.average_tenure_years == 13.0
    assert [(g.division, g.gender, g.subtotal) for g in headline(facts.groups)] == [
        ("성별합계", "male", True),
        ("성별합계", "female", True),
    ]
    assert len(facts.groups) == 4
    assert facts.groups[0].permanent == 290


def test_employees_prefer_a_grand_total_and_fall_back_to_every_row():
    grand = [
        staff("A", "남", "10"),
        staff("합계", "합계", "15", fyer_salary_totamt="900,000,000", jan_salary_am="60,000,000"),
        staff("B", "여", "5"),
    ]
    facts = employees(grand)
    assert facts is not None
    assert (facts.total, facts.average_salary) == (15, 60_000_000)
    plain = employees([staff("A", "남", "10"), staff("B", "여", "5", reform_bfe_emp_co_rgllbr="5")])
    assert plain is not None
    assert (plain.total, plain.average_salary, len(plain.groups)) == (15, None, 2)
    assert plain.groups[1].permanent == 5
    assert employees([staff("A", "-", "-")]) is None


def test_compensation_combines_every_table():
    tables = PayTables(
        approved=[
            row(se="등기이사", nmpr="4", gmtsck_confm_amount="-", fscl_year="-"),
            row(se="계", nmpr="10", gmtsck_confm_amount="36,000,000,000", fscl_year="-"),
        ],
        paid=[row(nmpr="9", mendng_totamt="28,052,000,000", jan_avrg_mendng_am="3,006,000,000")],
        by_type=[
            row(
                se="Registered director",
                nmpr="3",
                pymnt_totamt="26,981,000,000",
                psn1_avrg_pymntamt="8,302,000,000",
                stk_bsd_pd_mendng_totamt="-",
                rm="평균 3.3명",
            ),
            row(se="Auditor", nmpr="-", pymnt_totamt="-", psn1_avrg_pymntamt="-"),
            row(se="Total", nmpr="3", pymnt_totamt="26,981,000,000", psn1_avrg_pymntamt="-"),
        ],
        directors=[
            row(
                nm="갑",
                ofcps="이 사",
                mendng_totamt="1,843,000,000",
                mendng_totamt_ct_incls_mendng="RSA 약정",
            ),
            row(
                nm="을",
                ofcps="대표이사",
                mendng_totamt="5,606,000,000",
                mendng_totamt_ct_incls_mendng="-",
            ),
        ],
        unregistered=[
            row(
                se="Unregistered executive",
                nmpr="989",
                fyer_salary_totamt="705,452,000,000",
                jan_salary_am="744,000,000",
                rm="-",
            )
        ],
    )
    pay = compensation(tables)
    assert pay is not None
    assert (pay.approved_cap, pay.paid_total, pay.headcount, pay.average) == (
        36_000_000_000,
        28_052_000_000,
        9,
        3_006_000_000,
    )
    assert [(g.category, g.total, g.note) for g in pay.by_type] == [
        ("Registered director", 26_981_000_000, "평균 3.3명")
    ]
    assert [(p.name, p.total, p.not_in_total) for p in pay.directors_over_500m] == [
        ("을", 5_606_000_000, None),
        ("갑", 1_843_000_000, "RSA 약정"),
    ]
    assert pay.top_paid == ()
    assert pay.unregistered_executives is not None
    assert (pay.unregistered_executives.headcount, pay.unregistered_executives.average) == (
        989,
        744_000_000,
    )
    assert compensation(PayTables()) is None


def test_multi_year_pay_tables_keep_the_newest_year():
    rows = [
        row(nm="갑", fscl_year="2025", mendng_totamt="900,000,000"),
        row(nm="갑", fscl_year="2024", mendng_totamt="800,000,000"),
        row(nm="을", fscl_year="2025", mendng_totamt="-"),
    ]
    assert [r.mendng_totamt for r in newest(rows)] == ["900,000,000", "-"]
    found = people(rows)
    assert [(p.name, p.total) for p in found] == [("갑", 900_000_000), ("을", None)]
    approved = compensation(PayTables(approved=[row(se="등기이사", gmtsck_confm_amount="5,000")]))
    assert approved is not None
    assert approved.approved_cap == 5_000
