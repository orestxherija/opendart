"""Audit facts and the shared periodic-report helpers: terms, opinions, fees, and flags."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opendart_mcp.core.errors import UpstreamError
from opendart_mcp.domain.periods import PeriodRef
from opendart_mcp.services.extracts import (
    checked,
    filed_text,
    gather_all,
    is_total,
    records,
    sources,
    term_ages,
)
from opendart_mcp.services.governance_audit import (
    audit_facts,
    audit_flags,
    changed,
    fee_scale,
    key_matters,
    opinion,
    opinion_rows,
    same_auditor,
    scale_note,
)
from opendart_mcp.services.periods import PeriodicReport, ResolvedPeriod


def row(**fields):
    return SimpleNamespace(**fields)


def opinion_row(term, auditor="가나회계법인", filed="적정의견", **fields):
    return row(fiscal_year=term, adtor=auditor, adt_opinion=filed, **fields)


def fee_row(term, fee, hours, **fields):
    return row(
        fiscal_year=term,
        adtor="가나회계법인",
        adt_cntrct_dtls_mendng=fee,
        adt_cntrct_dtls_time=hours,
        real_exc_dtls_mendng=fee,
        real_exc_dtls_time=hours,
        cn="분ㆍ반기 검토\n연결 감사",
        **fields,
    )


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (
            ["제57기 \n(당기)", "제57기 \n(당기)", "제56기\n(전기)", "제55기\n(전전기)"],
            [0, 0, 1, 2],
        ),
        (["제57기(당기)", "제56기(당기)", "제55기(당기)"], [0, 1, 2]),
        (["당기", "전기", "전전기"], [0, 1, 2]),
        (["2025", "2024", "2023"], [0, 1, 2]),
        (["57th (current)", "56th (prior)"], [0, 1]),
        (["Current term", "Prior term", "Two years prior"], [0, 1, 2]),
        (["A", "B", "A"], [0, 1, 0]),
        (["제57기(당기)", None, "-", "제56기(전기)"], [0, 0, 0, 1]),
        (["-", "-"], [0, 0]),
        ([], []),
    ],
)
def test_term_ages(labels, expected):
    assert term_ages(labels) == expected


@pytest.mark.parametrize(
    ("filed", "expected"),
    [
        ("적정의견", "unqualified"),
        ("적정", "unqualified"),
        ("한정의견", "qualified"),
        ("부적정의견", "adverse"),
        ("의견거절", "disclaimer"),
        ("Unqualified opinion", "unqualified"),
        ("Qualified", "qualified"),
        ("Disclaimer of opinion", "disclaimer"),
        ("검토의견 없음", None),
        (None, None),
    ],
)
def test_opinions(filed, expected):
    assert opinion(filed) == expected


def test_key_audit_matters_split_into_numbered_items():
    assert key_matters("1. 매출 인식\n2. 재고자산 평가") == ["매출 인식", "재고자산 평가"]
    assert key_matters("1. 메모리 재고 평가2. 매출차감의 정확성") == [
        "메모리 재고 평가",
        "매출차감의 정확성",
    ]
    assert key_matters("영업권 1.5조원 손상검토") == ["영업권 1.5조원 손상검토"]
    assert key_matters("해당사항 없음") == []
    assert key_matters("-") == []


def test_auditors_compare_without_firm_suffixes():
    assert same_auditor("삼정회계법인", "삼정KPMG회계법인") is True
    assert same_auditor("한영회계법인", "삼일회계법인") is False
    assert same_auditor("회계법인", "삼일회계법인") is None
    assert changed("한영회계법인", "삼일회계법인") is True
    assert changed("한영회계법인", None) is None


@pytest.mark.parametrize(
    ("fee", "hours", "expected"),
    [
        ("8,100", "81,000", 1_000_000),
        ("150,000", "1,500", 1_000),
        ("150,000,000", "1,500", 1),
        ("5", "1,000,000", None),
        ("-", "1,500", None),
    ],
)
def test_fee_units_are_inferred_from_the_hourly_rate(fee, hours, expected):
    assert fee_scale([fee_row("제57기(당기)", fee, hours)]) == expected


def test_old_fee_columns_also_give_the_unit():
    old = row(fiscal_year="2019", mendng="120,000", tot_reqre_time="1,200")
    assert fee_scale([old]) == 1_000
    assert fee_scale([]) is None


def test_scale_notes():
    assert scale_note(1) is None
    assert "KRW million" in (scale_note(1_000_000) or "")
    assert "could not be inferred" in (scale_note(None) or "")


def test_opinion_rows_drop_duplicates_and_number_years():
    rows = [
        opinion_row(
            "제57기 \n(당기)", core_adt_matter="1. 매출\n2. 재고", emphs_matter="해당사항 없음"
        ),
        opinion_row(
            "제57기 \n(당기)", core_adt_matter="1. 매출\n2. 재고", emphs_matter="해당사항 없음"
        ),
        opinion_row("제56기\n(전기)", auditor="다라회계법인"),
    ]
    history = opinion_rows(rows, 2025)
    assert [(y.fiscal_year, y.auditor) for y in history] == [
        (2025, "가나회계법인"),
        (2024, "다라회계법인"),
    ]
    current = history[0]
    assert (current.opinion, current.emphasis, current.key_audit_matters) == (
        "unqualified",
        None,
        ["매출", "재고"],
    )
    assert current.term_as_filed == "제57기 (당기)"


def test_audit_facts_take_the_worst_current_opinion_and_scale_fees():
    history = opinion_rows(
        [
            opinion_row("제57기(당기)"),
            opinion_row(
                "제57기(당기)", filed="한정의견", emphs_matter="계속기업 가정에 관한 불확실성"
            ),
            opinion_row("제56기(전기)", auditor="다라회계법인"),
        ],
        2025,
    )
    fees = [fee_row("제57기(당기)", "300", "2,000"), fee_row("제56기(전기)", "250", "1,900")]
    services = [
        row(
            fiscal_year="제57기(당기)",
            cntrct_cncls_de="2025.03",
            servc_cn="세무자문",
            servc_exc_pd="2025.03~2025.12",
            servc_mendng="20",
            rm="가나회계법인",
        ),
        row(
            fiscal_year="제56기(전기)",
            cntrct_cncls_de="-",
            servc_cn="-",
            servc_exc_pd="-",
            servc_mendng="-",
            rm="-",
        ),
        row(
            fiscal_year="제56기(전기)",
            cntrct_cncls_de="2024.05",
            servc_cn="ESG 인증",
            servc_exc_pd="-",
            servc_mendng="10",
            rm="-",
        ),
    ]
    facts = audit_facts(history, fees, services, fiscal_year=2025, detailed=False)
    assert facts is not None
    assert (facts.opinion, facts.opinion_as_filed) == ("qualified", "한정의견")
    assert facts.emphasis == "계속기업 가정에 관한 불확실성"
    assert (facts.prior_auditor, facts.auditor_changed_vs_prior_year) == ("다라회계법인", True)
    assert facts.fee_scale == 1_000_000
    assert [(f.fiscal_year, f.contract_fee, f.actual_hours) for f in facts.fees] == [
        (2025, 300_000_000, 2000),
        (2024, 250_000_000, 1900),
    ]
    assert facts.fees[0].scope is None
    assert [(s.fiscal_year, s.fee, s.note) for s in facts.non_audit_services] == [
        (2025, 20_000_000, "가나회계법인")
    ]
    assert facts.history is None
    detailed = audit_facts(history, fees, services, fiscal_year=2025, detailed=True)
    assert detailed is not None
    assert [s.service for s in detailed.non_audit_services] == ["세무자문", "ESG 인증"]
    assert detailed.fees[0].scope == "분ㆍ반기 검토 연결 감사"
    assert detailed.history == history


def test_audit_facts_without_tables_or_current_rows():
    assert audit_facts([], [], [], fiscal_year=2025, detailed=False) is None
    facts = audit_facts([], [fee_row("2025", "9", "-")], [], fiscal_year=2025, detailed=False)
    assert facts is not None
    assert (facts.auditor, facts.opinion, facts.fee_scale) == (None, None, None)
    assert facts.fees[0].contract_fee == 9


def test_flags_cover_modified_opinions_going_concern_and_auditor_changes():
    history = opinion_rows(
        [
            opinion_row(
                "2025", filed="의견거절", core_adt_matter="1. " + "계속기업 존속능력 " * 30
            ),
            opinion_row("2024", auditor="다라회계법인"),
        ],
        2025,
    )
    facts = audit_facts(history, [], [], fiscal_year=2025, detailed=False)
    assert facts is not None
    flags = audit_flags(facts, history, fiscal_year=2025, label="FY2025")
    assert [flag.kind for flag in flags] == ["modified_opinion", "going_concern", "auditor_change"]
    assert flags[0].detail == "Disclaimer of opinion for FY2025, filed as 의견거절."
    assert flags[1].detail.endswith("...")
    assert flags[2].detail == "Auditor changed from 다라회계법인 to 가나회계법인."
    clean = opinion_rows([opinion_row("2025"), opinion_row("2024")], 2025)
    clean_facts = audit_facts(clean, [], [], fiscal_year=2025, detailed=False)
    assert clean_facts is not None
    assert audit_flags(clean_facts, clean, fiscal_year=2025, label="FY2025") == []


def test_filed_text_and_totals():
    assert filed_text("해당사항 없음") is None
    assert filed_text("N/A") is None
    assert filed_text("  감사\n  의견 ") == "감사 의견"
    assert is_total("합 계")
    assert is_total("Total")
    assert not is_total("Public offering")


def test_sources_skip_invalid_numbers_and_title_the_report():
    report = PeriodicReport(
        PeriodRef(2025, "FY"), None, "20260310002820", "Annual Report (2025.12)", None
    )
    found = sources(["20260310002820", None, "bad", "20260310002820", "20250310000001"], report)
    assert [(s.filing_number, s.title) for s in found] == [
        ("20260310002820", "Annual Report (2025.12)"),
        ("20250310000001", None),
    ]


def test_checked_names_the_report_or_the_probed_periods():
    report = PeriodicReport(
        PeriodRef(2025, "FY"), None, "20260310002820", "Annual Report (2025.12)", None
    )
    assert (
        checked(ResolvedPeriod((PeriodRef(2025, "FY"),), report, None))
        == '"Annual Report (2025.12)"'
    )
    refs = (
        PeriodRef(2026, "Q3"),
        PeriodRef(2026, "H1"),
        PeriodRef(2026, "Q1"),
        PeriodRef(2025, "FY"),
    )
    assert checked(ResolvedPeriod(refs, None, "guessed")) == "Q3 2026, H1 2026, Q1 2026"


def test_records_read_containers_safely():
    assert records(row(list=[1, 2])) == [1, 2]
    assert records(row(group=[3]), "group") == [3]
    assert records(row(list=None)) == []


@pytest.mark.anyio
async def test_gather_all_raises_the_first_failure_after_every_call_ends():
    finished = []

    async def ok(name):
        finished.append(name)
        return name

    async def fail():
        raise UpstreamError("upstream down")

    assert await gather_all([ok("a"), ok("b")]) == ["a", "b"]
    with pytest.raises(UpstreamError, match="upstream down"):
        await gather_all([fail(), ok("c")])
    assert finished == ["a", "b", "c"]
