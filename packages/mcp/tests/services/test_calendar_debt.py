"""Debt maturities merged into the corporate-action calendar: items, coverage notes, failures."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.calendar import BondsDue, CalendarItem, DebtMaturities
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.errors import DataSourceError
from opendart_mcp.core.errors import QuotaExhaustedError, UpstreamError
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services import calendar_debt, calendar_items
from opendart_mcp.services.companies import Company

COMPANY = Company(
    ref=CompanyRef(
        name="Example Co.",
        korean_name="예시",
        corp_code="00126380",
        stock_code="005930",
        market="KOSPI",
    ),
    fye_month=3,
    profile=None,
)
WINDOW = DateWindow(dt.date(2026, 10, 22), dt.date(2027, 1, 20))
H1 = PeriodRef(2026, "H1", end_date=dt.date(2026, 6, 30))
NUMBER = "20260814001234"


def maturity(**details):
    return CalendarItem(
        dt.date(2026, 12, 1),
        COMPANY.corp_code,
        "debt_maturity",
        "debt_securities",
        NUMBER,
        {"event": "Debt maturity", **details},
    )


def reader(found=None, error=None):
    async def fake(state, company, window):
        assert (company, window) == (COMPANY, WINDOW)
        if error is not None:
            raise error
        return found

    return fake


def test_the_subject_carries_both_names_and_the_fiscal_year_end():
    subject = calendar_items.subject(COMPANY)
    assert (subject.corp_code, subject.names, subject.fye_month) == (
        "00126380",
        ("예시", "Example Co."),
        3,
    )


@pytest.mark.anyio
async def test_maturities_become_calendar_items_with_coverage_notes(monkeypatch):
    bonds = BondsDue(H1, dt.date(2026, 6, 30), 803_572_000_000, 1_213_572_000_000)
    item = maturity(instrument="Corporate Bonds", face_value=300_000_000_000, coupon=3.5)
    found = DebtMaturities((item,), H1, bonds)
    monkeypatch.setattr(calendar_debt, "read_maturities", reader(found))
    (output,), notes = await calendar_debt.debt_maturities(None, COMPANY, WINDOW)
    assert (output.date, output.action, output.source_kind) == (
        dt.date(2026, 12, 1),
        "debt_maturity",
        "debt_securities",
    )
    assert output.company == COMPANY.ref
    assert output.details == {
        "event": "Debt maturity",
        "instrument": "Corporate Bonds",
        "face_value": 300_000_000_000,
        "coupon": 3.5,
    }
    assert output.dart_url.endswith(f"rcpNo={NUMBER}")
    assert notes == [
        calendar_debt.COVERAGE,
        "Example Co.: KRW 803,572 million of the KRW 1,213,572 million in corporate bonds outstanding at 2026-06-30 was due within a year of that date (H1 2026 report).",
    ]
    assert "issuance records" in notes[0]
    assert "get_debt_profile" in notes[0]


@pytest.mark.anyio
async def test_a_period_without_a_ladder_adds_only_the_coverage_note(monkeypatch):
    found = DebtMaturities((maturity(redeemed="partly"),), H1)
    monkeypatch.setattr(calendar_debt, "read_maturities", reader(found))
    (output,), notes = await calendar_debt.debt_maturities(None, COMPANY, WINDOW)
    assert output.details["redeemed"] == "partly"
    assert notes == [calendar_debt.COVERAGE]


def test_the_ladder_note_says_when_nothing_falls_due_within_a_year():
    fy = PeriodRef(2025, "FY")
    note = calendar_debt.ladder_note(
        COMPANY, BondsDue(fy, dt.date(2025, 12, 31), 0, 40_000_000_000)
    )
    assert note == (
        "Example Co.: none of the KRW 40,000 million in corporate bonds outstanding at 2025-12-31 was due within a year of that date (FY2025 report)."
    )


@pytest.mark.anyio
async def test_companies_without_debt_tables_add_no_notes(monkeypatch):
    monkeypatch.setattr(calendar_debt, "read_maturities", reader(DebtMaturities()))
    assert await calendar_debt.debt_maturities(None, COMPANY, WINDOW) == ([], [])


@pytest.mark.anyio
async def test_upstream_failures_are_noted_without_maturities(monkeypatch):
    monkeypatch.setattr(calendar_debt, "read_maturities", reader(error=UpstreamError("down")))
    assert await calendar_debt.debt_maturities(None, COMPANY, WINDOW) == (
        [],
        ["Debt maturities unavailable for Example Co.: down"],
    )


@pytest.mark.anyio
async def test_an_exhausted_quota_still_fails(monkeypatch):
    monkeypatch.setattr(
        calendar_debt, "read_maturities", reader(error=QuotaExhaustedError("quota"))
    )
    with pytest.raises(QuotaExhaustedError):
        await calendar_debt.debt_maturities(None, COMPANY, WINDOW)


@pytest.mark.anyio
async def test_an_analysis_data_source_failure_is_noted_like_an_upstream_one(monkeypatch):
    def factory(**bindings):
        async def read(subject, window):
            raise DataSourceError("Malformed debt table.", operation="det_scrits_isu_acmslt")

        return read

    monkeypatch.setattr(calendar_debt.calendar, "read_debt_maturities", factory)
    state = SimpleNamespace(require_gateway=None, today=lambda: WINDOW.start)
    assert await calendar_debt.debt_maturities(state, COMPANY, WINDOW) == (
        [],
        ["Debt maturities unavailable for Example Co.: Malformed debt table."],
    )
