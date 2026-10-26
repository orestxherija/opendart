"""get_capital_structure service: treasury fallbacks, row filtering, sections, and notes."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.services.capital import CapitalQuery, capital_structure

MOVES = ("stock_knd", "acqs_mth1", "acqs_mth2", "acqs_mth3", "bsis_qy", "change_qy_acqs")
MOVES += ("change_qy_dsps", "change_qy_incnr", "trmend_qy")
SHARES = {
    "rcept_no": "20260310002820",
    "se": "보통주",
    "istc_totqy": "1,000",
    "tesstk_co": "10",
    "distb_stock_co": "990",
    "stlm_dt": "2025-12-31",
}


@pytest.fixture
async def state(mcp_settings, sdk_settings, upstream, now):
    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/company.json", upstream.ok(corp_name="삼성전자", corp_cls="Y", acc_mt="12"))
    async with open_state(
        mcp_settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as opened:
        # Wait for the directory so company identity does not depend on load timing.
        await opened.directory.wait(5)
        yield opened


def treasury(*values, rm="-"):
    return dict(zip(MOVES, values, strict=True)) | {"rm": rm}


async def run(state, **arguments):
    query = CapitalQuery(company="00126380", period="FY", fiscal_year=2025, **arguments)
    return await capital_structure(state, query)


@pytest.mark.anyio
async def test_treasury_totals_are_added_up_when_no_total_rows_are_filed(state, upstream):
    upstream.records("/stockTotqySttus.json", SHARES)
    upstream.records(
        "/tesstkAcqsDspsSttus.json",
        treasury(
            "보통주",
            "배당가능이익 범위 이내 취득",
            "직접 취득",
            "장내 직접 취득",
            "10",
            "5",
            "-",
            "2",
            "13",
            rm="소각",
        ),
        treasury(
            "보통주",
            "배당가능이익 범위 이내 취득",
            "신탁계약에 의한 취득",
            "수탁자 보유물량",
            "1",
            "1",
            "1",
            "-",
            "1",
        ),
        treasury(
            "보통주", "배당가능이익 범위 이내 취득", "직접 취득", "소계", "10", "5", "-", "2", "13"
        ),
        treasury("우선주", "기타 취득", "기타 취득", "기타 취득", "-", "3", "-", "-", "3"),
        treasury("우선주", "기타 취득", "기타 취득", "기타 취득", "-", "-", "-", "-", "-"),
    )
    concise = await run(state, sections=("treasury_stock",))
    totals = [
        (r.share_class, r.begin, r.acquired, r.disposed, r.retired, r.end)
        for r in concise.treasury_stock
    ]
    assert totals == [("common", 11, 6, 1, 2, 14), ("preferred", None, 3, None, None, 3)]
    assert concise.treasury_stock_by_method is None
    detailed = await run(state, sections=("treasury_stock",), detailed=True)
    methods = detailed.treasury_stock_by_method
    assert [m.method for m in methods] == [
        "배당가능이익 범위 이내 취득 > 직접 취득 > 장내 직접 취득",
        "배당가능이익 범위 이내 취득 > 신탁계약에 의한 취득 > 수탁자 보유물량",
        "기타 취득",
    ]
    assert methods[0].note == "소각"


@pytest.mark.anyio
async def test_rows_without_dates_amounts_or_uses_are_dropped(state, upstream):
    upstream.records("/stockTotqySttus.json", SHARES)
    upstream.records(
        "/irdsSttus.json",
        {"isu_dcrs_de": "-", "isu_dcrs_stle": "해당사항 없음", "isu_dcrs_qy": "-"},
        {
            "isu_dcrs_de": "-",
            "isu_dcrs_stle": "전환권행사",
            "isu_dcrs_stock_knd": "보통주",
            "isu_dcrs_qy": "500",
        },
        {
            "isu_dcrs_de": "2020.01.02",
            "isu_dcrs_stle": "무상증자",
            "isu_dcrs_stock_knd": "보통주",
            "isu_dcrs_qy": "100",
        },
    )
    upstream.records(
        "/prvsrpCptalUseDtls.json",
        {"se_nm": "해당사항 없음", "tm": "-", "pay_de": "-", "pay_amount": "-"},
        {
            "se_nm": "전환사채",
            "tm": "3",
            "pay_de": "2017.03.02",
            "pay_amount": "5,000,000,000",
            "cptal_use_plan": "운영자금",
            "real_cptal_use_sttus": "운영자금 사용 완료",
            "mtrpt_cptal_use_plan_useprps": "-",
            "mtrpt_cptal_use_plan_prcure_amount": "-",
        },
    )
    result = await run(state, sections=("capital_changes", "use_of_proceeds"))
    assert [(c.date, c.category, c.shares) for c in result.capital_changes] == [
        (date(2020, 1, 2), "bonus issue", 100),
        (None, "conversion", 500),
    ]
    (private,) = result.use_of_proceeds
    assert (private.offering, private.kind, private.series) == ("private", "전환사채", None)
    assert (private.paid_on, private.amount_paid) == (date(2017, 3, 2), 5_000_000_000)
    assert (private.plan, private.actual_status) == ("운영자금", "운영자금 사용 완료")
    assert private.planned_amount is None


@pytest.mark.anyio
async def test_a_report_without_a_share_table_yet_falls_back_with_a_note(state, upstream):
    def by_period(request):
        if request.url.params["reprt_code"] == "11013":
            return upstream.rows(SHARES | {"rcept_no": "2026051"})
        return upstream.status("013")

    upstream.route("/stockTotqySttus.json", by_period)
    query = CapitalQuery(company="00126380", sections=("shares",))
    result = await capital_structure(state, query)
    assert (result.fiscal_year, result.period) == (2026, "Q1")
    assert result.period_end == date(2026, 3, 31)
    assert result.notes == [
        "No periodic report was found in the last 15 months; periods were chosen by filing deadlines.",
        "The Q3 2026 report has no share-count table yet; showing Q1 2026.",
    ]
    assert result.source_filings == []
    assert result.shares is not None
    assert result.shares[0].outstanding == 990


@pytest.mark.anyio
async def test_empty_results_keep_the_deadline_note(state):
    result = await capital_structure(state, CapitalQuery(company="00126380"))
    assert result.notes[0].startswith("No periodic report was found in the last 15 months")
    assert result.notes[1].startswith("No periodic report for Q3 2026, H1 2026, Q1 2026")
    assert result.sections == ["shares", "treasury_stock", "capital_changes", "use_of_proceeds"]
    assert result.treasury_stock == result.use_of_proceeds == []


@pytest.mark.anyio
async def test_detailed_results_omit_unrequested_sections(state, upstream):
    upstream.records("/stockTotqySttus.json", SHARES)
    result = await run(state, sections=("shares",), detailed=True)
    assert result.shares is not None
    assert result.treasury_stock is result.treasury_stock_by_method is None
    assert upstream.count("/tesstkAcqsDspsSttus.json") == 0
