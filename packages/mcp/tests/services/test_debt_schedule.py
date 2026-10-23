"""The calendar's debt maturity schedule: reports read, window, probing, and the bond ladder."""

from __future__ import annotations

import datetime as dt

import pytest

from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.domain.dates import DateWindow
from opendart_mcp.domain.periods import PeriodRef
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.debt import maturity_schedule

SAMSUNG = Company(
    ref=CompanyRef(
        name="SAMSUNG ELECTRONICS CO,.LTD",
        korean_name="삼성전자",
        corp_code="00126380",
        stock_code="005930",
        market="KOSPI",
    ),
    fye_month=12,
    profile=None,
)
FORWARD = DateWindow(dt.date(2026, 10, 22), dt.date(2027, 12, 31))
ISSUANCE = "/detScritsIsuAcmslt.json"
BALANCES = "/cprndNrdmpBlce.json"


def report(number, title):
    return {
        "corp_cls": "Y",
        "corp_name": "SAMSUNG ELECTRONICS CO,.LTD",
        "corp_code": "00126380",
        "stock_code": "005930",
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": "삼성전자",
        "rcept_dt": number[:8],
        "rm": "",
    }


def issue_record(number, maturity, **overrides):
    record = {
        "rcept_no": number,
        "corp_code": "00126380",
        "isu_cmpny": "삼성전자㈜",
        "scrits_knd_nm": "Corporate Bonds",
        "isu_mth_nm": "Public offering",
        "isu_de": "2025.05.02",
        "facvalu_totamt": "100,000,000,000",
        "intrt": "3.10",
        "evl_grad_instt": "AA+(한국기업평가)",
        "mtd": maturity,
        "repy_at": "미상환",
        "mngt_cmpny": "가나증권",
    }
    return record | overrides


def balance(number, within, total):
    return {
        "rcept_no": number,
        "remndr_exprtn1": "Unredeemed balance",
        "remndr_exprtn2": "Total",
        "yy1_below": within,
        "yy2_excess_yy3_below": "50,000,000,000",
        "sm": total,
    }


def by_period(upstream, table):
    """Answer with the rows filed for (bsns_year, reprt_code), else no data."""

    def answer(request):
        found = table.get((request.url.params["bsns_year"], request.url.params["reprt_code"]))
        return upstream.rows(*found) if found else upstream.status("013")

    return answer


def periods(upstream, path):
    return [(p["bsns_year"], p["reprt_code"]) for p in upstream.params(path)]


async def run(mcp_settings, sdk_settings, upstream, now, window=FORWARD):
    async with open_state(
        mcp_settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as state:
        return await maturity_schedule(state, SAMSUNG, window=window)


def half_year_and_annual(upstream):
    upstream.records(
        "/list.json",
        report("20260814001234", "Semi-Annual Report (2026.06)"),
        report("20260310002820", "Annual Report (2025.12)"),
    )
    upstream.route(
        ISSUANCE,
        by_period(
            upstream,
            {
                ("2026", "11012"): [
                    issue_record("20260814001234", "2026.12.15", scrits_knd_nm="Commercial Paper"),
                    issue_record("20260814001234", "2026.10.01"),
                ],
                ("2025", "11011"): [
                    issue_record("20260310002820", "2027.05.02", repy_at="일부상환"),
                    issue_record("20260310002820", "2026.12.15", scrits_knd_nm="Commercial Paper"),
                ],
            },
        ),
    )
    upstream.route(
        BALANCES,
        by_period(
            upstream,
            {("2026", "11012"): [balance("20260814001234", "70,000,000,000", "120,000,000,000")]},
        ),
    )


@pytest.mark.anyio
async def test_the_latest_report_and_the_prior_annual_issuance_are_read(
    mcp_settings, sdk_settings, upstream, now
):
    half_year_and_annual(upstream)
    schedule = await run(mcp_settings, sdk_settings, upstream, now)
    assert [(m.date, m.instrument, m.redeemed) for m in schedule.maturities] == [
        (dt.date(2026, 12, 15), "Commercial Paper", "no"),
        (dt.date(2027, 5, 2), "Corporate Bonds", "partly"),
    ]
    assert schedule.maturities[1].face_value == 100_000_000_000
    assert all(m.issuer is None for m in schedule.maturities)
    assert schedule.period == PeriodRef(2026, "H1")
    assert schedule.bonds is not None
    assert (schedule.bonds.total, schedule.bonds.buckets[0].amount) == (
        120_000_000_000,
        70_000_000_000,
    )
    assert sorted(periods(upstream, ISSUANCE)) == [("2025", "11011"), ("2026", "11012")]
    assert periods(upstream, BALANCES) == [("2026", "11012")]


@pytest.mark.anyio
async def test_the_window_may_start_before_today(mcp_settings, sdk_settings, upstream, now):
    half_year_and_annual(upstream)
    window = DateWindow(dt.date(2026, 9, 1), dt.date(2026, 12, 31))
    schedule = await run(mcp_settings, sdk_settings, upstream, now, window)
    assert [m.date for m in schedule.maturities] == [dt.date(2026, 10, 1), dt.date(2026, 12, 15)]


@pytest.mark.anyio
async def test_an_annual_report_without_debt_tables_is_an_empty_schedule(
    mcp_settings, sdk_settings, upstream, now
):
    upstream.records("/list.json", report("20260310002820", "Annual Report (2025.12)"))
    schedule = await run(mcp_settings, sdk_settings, upstream, now)
    assert (schedule.maturities, schedule.period, schedule.bonds) == ([], None, None)
    assert periods(upstream, ISSUANCE) == [("2025", "11011")]
    assert periods(upstream, BALANCES) == [("2025", "11011")]


@pytest.mark.anyio
async def test_candidate_periods_are_probed_without_a_listed_report(
    mcp_settings, sdk_settings, upstream, now
):
    upstream.route("/list.json", upstream.status("013"))
    rows = {("2026", "11013"): [issue_record("20260515000777", "2027.03.31")]}
    upstream.route(ISSUANCE, by_period(upstream, rows))
    schedule = await run(mcp_settings, sdk_settings, upstream, now)
    assert schedule.period == PeriodRef(2026, "Q1")
    assert [m.date for m in schedule.maturities] == [dt.date(2027, 3, 31)]
    assert schedule.bonds is None
    assert periods(upstream, BALANCES) == [("2026", "11014"), ("2026", "11012"), ("2026", "11013")]


@pytest.mark.anyio
async def test_without_tables_in_the_latest_report_the_prior_annual_report_is_read(
    mcp_settings, sdk_settings, upstream, now
):
    upstream.records("/list.json", report("20260814001234", "Semi-Annual Report (2026.06)"))
    annual = {("2025", "11011"): [issue_record("20260310002820", "2026.12.01", scrits_knd_nm="CP")]}
    upstream.route(ISSUANCE, by_period(upstream, annual))
    upstream.route(
        BALANCES,
        by_period(
            upstream,
            {("2025", "11011"): [balance("20260310002820", "-", "50,000,000,000")]},
        ),
    )
    schedule = await run(mcp_settings, sdk_settings, upstream, now)
    assert schedule.period == PeriodRef(2025, "FY")
    assert [m.instrument for m in schedule.maturities] == ["CP"]
    assert schedule.bonds is not None
    assert schedule.bonds.total == 50_000_000_000
    assert sorted(periods(upstream, BALANCES)) == [("2025", "11011"), ("2026", "11012")]
    # The prior annual issuance record is read once and then served from the cache.
    assert upstream.count(ISSUANCE) == 2


@pytest.mark.anyio
async def test_no_tables_anywhere_is_an_empty_schedule(mcp_settings, sdk_settings, upstream, now):
    upstream.records("/list.json", report("20260814001234", "Semi-Annual Report (2026.06)"))
    schedule = await run(mcp_settings, sdk_settings, upstream, now)
    assert (schedule.maturities, schedule.period) == ([], None)
    assert sorted(periods(upstream, BALANCES)) == [("2025", "11011"), ("2026", "11012")]
