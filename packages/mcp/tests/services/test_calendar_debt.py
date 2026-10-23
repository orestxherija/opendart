"""Debt maturities merged into the corporate-action calendar: items, coverage notes, failures."""

from __future__ import annotations

import datetime as dt

import pytest

from opendart_mcp.core.errors import QuotaExhaustedError, UpstreamError
from opendart_mcp.domain.dates import DateWindow
from opendart_mcp.domain.periods import PeriodRef
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.models.debt import DebtMaturity, LadderBucket, LadderEntry
from opendart_mcp.services import calendar_debt
from opendart_mcp.services.companies import Company
from opendart_mcp.services.debt import MaturitySchedule

COMPANY = Company(
    ref=CompanyRef(name="Example Co.", corp_code="00126380", stock_code="005930", market="KOSPI"),
    fye_month=12,
    profile=None,
)
WINDOW = DateWindow(dt.date(2026, 10, 22), dt.date(2027, 1, 20))
H1 = PeriodRef(2026, "H1", end_date=dt.date(2026, 6, 30))
BONDS = LadderEntry(
    instrument="corporate_bonds",
    buckets=[
        LadderBucket(maturity_bucket="<=1y", amount=803_572_000_000),
        LadderBucket(maturity_bucket="1-2y", amount=410_000_000_000),
    ],
    total=1_213_572_000_000,
)


def schedule(found=None, error=None):
    async def fake(state, company, *, window):
        assert window == WINDOW
        if error is not None:
            raise error
        return found

    return fake


@pytest.mark.anyio
async def test_maturities_become_calendar_items_with_coverage_notes(monkeypatch):
    found = MaturitySchedule(
        [
            DebtMaturity(
                date=dt.date(2026, 12, 1),
                instrument="Corporate Bonds",
                face_value=300_000_000_000,
                filing_number="20260814001234",
                coupon=3.5,
                redeemed="no",
            ),
            DebtMaturity(
                date=dt.date(2027, 3, 1), instrument="Late", filing_number="20260814001234"
            ),
            DebtMaturity(date=dt.date(2026, 11, 1), instrument="No source"),
        ],
        H1,
        BONDS,
    )
    monkeypatch.setattr(calendar_debt, "maturity_schedule", schedule(found))
    (item,), notes = await calendar_debt.debt_maturities(None, COMPANY, WINDOW)
    assert (item.date, item.action, item.source_kind) == (
        dt.date(2026, 12, 1),
        "debt_maturity",
        "debt_securities",
    )
    assert item.details == {
        "event": "Debt maturity",
        "instrument": "Corporate Bonds",
        "face_value": 300_000_000_000,
        "coupon": 3.5,
        "redeemed": "no",
    }
    assert item.dart_url.endswith("rcpNo=20260814001234")
    assert notes == [
        calendar_debt.COVERAGE,
        "Example Co.: KRW 803,572 million of the KRW 1,213,572 million in corporate bonds outstanding at 2026-06-30 was due within a year of that date (H1 2026 report).",
    ]
    assert "issuance records" in notes[0]
    assert "get_debt_profile" in notes[0]


@pytest.mark.anyio
async def test_partly_redeemed_issues_keep_their_face_value_and_say_so(monkeypatch):
    partly = DebtMaturity(
        date=dt.date(2026, 12, 1),
        instrument="Corporate Bonds",
        face_value=143_490_000_000,
        filing_number="20260310002820",
        coupon=7.7,
        redeemed="partly",
        issuer="Samsung Display",
    )
    monkeypatch.setattr(
        calendar_debt, "maturity_schedule", schedule(MaturitySchedule([partly], H1))
    )
    (item,), notes = await calendar_debt.debt_maturities(None, COMPANY, WINDOW)
    assert item.details["face_value"] == 143_490_000_000
    assert item.details["redeemed"] == "partly"
    assert item.details["issuer"] == "Samsung Display"
    assert "amount" not in item.details
    assert notes == [calendar_debt.COVERAGE]


@pytest.mark.anyio
async def test_the_ladder_note_says_when_nothing_falls_due_within_a_year(monkeypatch):
    later = LadderEntry(
        instrument="corporate_bonds",
        buckets=[LadderBucket(maturity_bucket="2-3y", amount=40_000_000_000)],
        total=40_000_000_000,
    )
    found = MaturitySchedule([], PeriodRef(2025, "FY"), later)
    monkeypatch.setattr(calendar_debt, "maturity_schedule", schedule(found))
    items, notes = await calendar_debt.debt_maturities(None, COMPANY, WINDOW)
    assert items == []
    assert notes[1] == (
        "Example Co.: none of the KRW 40,000 million in corporate bonds outstanding at 2025-12-31 was due within a year of that date (FY2025 report)."
    )


@pytest.mark.anyio
async def test_companies_without_debt_tables_add_no_notes(monkeypatch):
    monkeypatch.setattr(calendar_debt, "maturity_schedule", schedule(MaturitySchedule([])))
    assert await calendar_debt.debt_maturities(None, COMPANY, WINDOW) == ([], [])


@pytest.mark.anyio
async def test_upstream_failures_are_noted_without_maturities(monkeypatch):
    monkeypatch.setattr(calendar_debt, "maturity_schedule", schedule(error=UpstreamError("down")))
    assert await calendar_debt.debt_maturities(None, COMPANY, WINDOW) == (
        [],
        ["Debt maturities unavailable for Example Co.: down"],
    )


@pytest.mark.anyio
async def test_an_exhausted_quota_still_fails(monkeypatch):
    monkeypatch.setattr(
        calendar_debt, "maturity_schedule", schedule(error=QuotaExhaustedError("quota"))
    )
    with pytest.raises(QuotaExhaustedError):
        await calendar_debt.debt_maturities(None, COMPANY, WINDOW)
