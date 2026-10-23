"""Share counts by class and the periodic-report row helpers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from opendart.models.periodic_reports import StockTotqySttusResponseListItem
from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.domain.periods import PeriodRef
from opendart_mcp.models.capital import ShareClassRow
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.shares import (
    blank,
    fetch_share_counts,
    is_note,
    is_total,
    items_of,
    latest_share_counts,
    parse_share_counts,
    period_args,
    share_class,
    shares_outstanding,
    sum_known,
    trim,
)

COUNTS = ("isu_stock_totqy", "now_to_isu_stock_totqy", "now_to_dcrs_stock_totqy", "redc")
COUNTS += ("profit_incnr", "rdmstk_repy", "etc", "istc_totqy", "tesstk_co", "distb_stock_co")
FY2025 = PeriodRef(2025, "FY")


def row(se, *values, number="20260310002820"):
    cells = dict(zip(COUNTS, values, strict=True))
    return {"rcept_no": number, "se": se, "stlm_dt": "2025-12-31", **cells}


COMMON_VALUES = ("100", "90", "10", "-", "10", "-", "-", "80", "5", "75")
COMMON = row("보통주", *COMMON_VALUES)
PREFERRED = row("우선주", "50", "20", "-", "-", "-", "-", "-", "20", "2", "18")
TOTAL = row("합계", "150", "110", "10", "-", "10", "-", "-", "100", "7", "93")
NOTE = row("비고", "-", "-", "-", "-", "자사주소각", "-", "-", "-", "-", "-")
DASHES = row("보통주", *["-"] * 10)


def items(*rows):
    return [StockTotqySttusResponseListItem.model_validate(r) for r in rows]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("보통주", "common"),
        ("우선주", "preferred"),
        ("전환우선주", "preferred"),
        ("Common Stock", "common"),
        ("Preferred shares", "preferred"),
        (" 종류주식 ", "종류주식"),
        ("-", None),
        (None, None),
    ],
)
def test_share_classes_are_normalized(text, expected):
    assert share_class(text) == expected


@pytest.mark.parametrize("text", ["Total", "합계", "합 계", "소계", "Subtotal", "총계"])
def test_total_labels(text):
    assert is_total(text)
    assert not is_note(text)


@pytest.mark.parametrize("text", ["Note", "비고", "Remarks"])
def test_note_labels(text):
    assert is_note(text)
    assert not is_total(text)


def test_plain_labels_are_neither_totals_nor_notes():
    assert not is_total("보통주")
    assert not is_total(None)
    assert not is_note("삼성물산")


def test_counts_parse_classes_totals_and_the_note_row():
    counts = parse_share_counts(items(COMMON, PREFERRED, TOTAL, NOTE), FY2025)
    assert counts is not None
    assert counts.filing_number == "20260310002820"
    assert counts.as_of == date(2025, 12, 31)
    assert [c.share_class for c in counts.classes] == ["common", "preferred"]
    assert counts.classes[0] == ShareClassRow(
        share_class="common",
        authorized=100,
        issued=80,
        treasury=5,
        outstanding=75,
        issued_to_date=90,
        decreased_to_date=10,
        retired_from_profits=10,
    )
    assert counts.total is not None
    assert counts.total.share_class == "total"
    assert (counts.issued, counts.treasury, counts.outstanding) == (100, 7, 93)
    assert counts.primary is counts.classes[0]
    assert counts.note == "retired from profits: 자사주소각"


def test_without_a_total_row_counts_are_added_up_over_classes():
    counts = parse_share_counts(items(COMMON, PREFERRED), FY2025)
    assert counts is not None
    assert counts.total is None
    assert counts.note is None
    assert (counts.issued, counts.treasury, counts.outstanding) == (100, 7, 93)


def test_the_first_class_is_primary_without_common_shares():
    counts = parse_share_counts(items(PREFERRED, TOTAL), FY2025)
    assert counts is not None
    assert counts.primary is not None
    assert counts.primary.share_class == "preferred"


def test_a_total_row_alone_has_no_primary_class():
    counts = parse_share_counts(items(TOTAL), FY2025)
    assert counts is not None
    assert counts.classes == ()
    assert counts.primary is None
    assert counts.issued == 100


def test_a_blank_class_counts_as_common_shares():
    counts = parse_share_counts(items(row("-", *COMMON_VALUES)), FY2025)
    assert counts is not None
    assert counts.classes[0].share_class == "common"


def test_tables_of_dashes_have_no_counts():
    assert parse_share_counts(items(DASHES, NOTE), FY2025) is None
    assert parse_share_counts([], FY2025) is None


def test_row_helpers():
    assert sum_known([1, None, 2]) == 3
    assert sum_known([None, None]) is None
    full = ShareClassRow(share_class="common", authorized=1, issued_to_date=2)
    assert not blank(full, "share_class")
    assert blank(ShareClassRow(share_class="common"), "share_class")
    assert trim(full, ("issued_to_date",)) == ShareClassRow(share_class="common", authorized=1)
    assert items_of(None) == []


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
        yield opened


def annual_report(upstream):
    upstream.records(
        "/list.json",
        {
            "corp_code": "00126380",
            "corp_name": "SAMSUNG ELECTRONICS CO,.LTD",
            "report_nm": "Annual Report (2025.12)",
            "rcept_no": "20260310002820",
            "rcept_dt": "20260310",
        },
    )


@pytest.mark.anyio
async def test_fetch_uses_the_period_arguments(state, upstream):
    upstream.records("/stockTotqySttus.json", COMMON, TOTAL)
    company = await state.companies.resolve("00126380")
    assert period_args(company, FY2025) == {
        "corporation_code": "00126380",
        "fiscal_year": "2025",
        "report_period": "11011",
    }
    counts = await fetch_share_counts(state, company, FY2025)
    assert counts is not None
    assert counts.outstanding == 93
    query = upstream.params("/stockTotqySttus.json")[0]
    assert (query["bsns_year"], query["reprt_code"]) == ("2025", "11011")


@pytest.mark.anyio
async def test_shares_outstanding_reads_the_latest_report(state, upstream):
    annual_report(upstream)
    upstream.records("/stockTotqySttus.json", COMMON, PREFERRED, TOTAL)
    company = await state.companies.resolve("00126380")
    assert await shares_outstanding(state, company) == 93
    counts = await latest_share_counts(state, company)
    assert counts is not None
    assert counts.ref == FY2025


@pytest.mark.anyio
async def test_shares_outstanding_is_none_without_data(state):
    company = await state.companies.resolve("00126380")
    assert await shares_outstanding(state, company, period="FY", fiscal_year=2024) is None


@pytest.mark.anyio
@pytest.mark.parametrize(("ref", "calls"), [(FY2025, 1), (PeriodRef(2026, "Q3"), 2)])
async def test_unsettled_share_counts_are_fetched_again_sooner(sdk, upstream, ref, calls):
    clock = [0.0]
    cache = TTLCache(max_weight=1000, clock=lambda: clock[0])
    gateway = Gateway(sdk, cache=cache, concurrency=4, retry_delay=0)
    state = SimpleNamespace(require_gateway=lambda: gateway, today=lambda: date(2026, 10, 22))
    company = Company(
        ref=CompanyRef(name="Example", corp_code="00126380"), fye_month=12, profile=None
    )
    upstream.records("/stockTotqySttus.json", COMMON, TOTAL)
    for _ in range(2):
        assert await fetch_share_counts(state, company, ref) is not None
        clock[0] += 16 * 60  # past the filing-list lifetime, well within a day
    assert upstream.count("/stockTotqySttus.json") == calls
