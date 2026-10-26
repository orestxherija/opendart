"""Debt maturities as calendar items, with the latest corporate-bond ladder's totals."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_analysis.calendar import (
    BondsDue,
    CalendarSubject,
    DebtMaturities,
    bonds_due,
    read_debt_maturities,
    schedule_maturities,
)
from opendart_analysis.debt import Bucket, Ladder, Maturity, MaturitySchedule
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.domain.periods import PeriodRef

WINDOW = DateWindow(dt.date(2026, 10, 22), dt.date(2027, 1, 20))
H1 = PeriodRef(2026, "H1", end_date=dt.date(2026, 6, 30))
NUMBER = "20260814001234"


def maturity(day, instrument="Corporate Bonds", filing_number=NUMBER, **fields):
    values = {"face_value": None, "coupon": None, "redeemed": None, "issuer": None, **fields}
    return Maturity(date=day, instrument=instrument, filing_number=filing_number, **values)


def ladder(*buckets):
    amounts = tuple(Bucket(bucket, amount) for bucket, amount in buckets)
    total = sum(amount for _, amount in buckets)
    return Ladder("corporate_bonds", amounts, total, None, None, None, None, ())


def test_maturities_in_the_window_with_a_filing_become_items():
    schedule = MaturitySchedule(
        (
            maturity(
                dt.date(2026, 12, 1),
                face_value=300_000_000_000,
                coupon=3.5,
                redeemed="no",
            ),
            maturity(dt.date(2027, 3, 1), "Late"),
            maturity(dt.date(2026, 11, 1), "No source", filing_number=None),
            maturity(dt.date(2026, 11, 2), "Bad source", filing_number="-"),
        ),
        H1,
    )
    found = schedule_maturities("00126380", schedule, WINDOW, fye_month=12)
    (item,) = found.items
    assert (item.date, item.corp_code, item.action, item.source_kind, item.filing_number) == (
        dt.date(2026, 12, 1),
        "00126380",
        "debt_maturity",
        "debt_securities",
        NUMBER,
    )
    assert item.details == {
        "event": "Debt maturity",
        "instrument": "Corporate Bonds",
        "face_value": 300_000_000_000,
        "coupon": 3.5,
        "redeemed": "no",
    }
    assert (found.period, found.bonds) == (H1, None)


def test_partly_redeemed_issues_keep_their_face_value_and_say_so():
    partly = maturity(
        dt.date(2026, 12, 1),
        face_value=143_490_000_000,
        coupon=7.7,
        redeemed="partly",
        issuer="Samsung Display",
    )
    found = schedule_maturities("00126380", MaturitySchedule((partly,), H1), WINDOW, fye_month=12)
    (item,) = found.items
    assert item.details["face_value"] == 143_490_000_000
    assert item.details["redeemed"] == "partly"
    assert item.details["issuer"] == "Samsung Display"


def test_bond_totals_come_from_the_latest_ladder():
    bonds = ladder(("<=1y", 803_572_000_000), ("1-2y", 410_000_000_000))
    assert bonds_due(MaturitySchedule((), H1, bonds), fye_month=12) == BondsDue(
        H1, dt.date(2026, 6, 30), 803_572_000_000, 1_213_572_000_000
    )


def test_a_period_without_an_end_date_ends_with_the_fiscal_year():
    later = ladder(("2-3y", 40_000_000_000))
    totals = bonds_due(MaturitySchedule((), PeriodRef(2025, "FY"), later), fye_month=3)
    assert totals == BondsDue(PeriodRef(2025, "FY"), dt.date(2025, 3, 31), 0, 40_000_000_000)


def test_no_period_or_no_ladder_has_no_totals():
    assert bonds_due(MaturitySchedule(), fye_month=12) is None
    assert bonds_due(MaturitySchedule((), H1), fye_month=12) is None


@pytest.mark.anyio
async def test_the_reader_resolves_the_latest_period_and_reads_its_tables():
    filed = {
        ("det_scrits_isu_acmslt", "11012"): [
            SimpleNamespace(
                filing_number=NUMBER,
                isu_cmpny="자회사",
                scrits_knd_nm="Commercial Paper",
                isu_mth_nm="Public offering",
                isu_de="2026.02.21",
                facvalu_totamt="20,000,000,000",
                intrt="3.36",
                evl_grad_instt="-",
                mtd="2026.12.04",
                repy_at="미상환",
            )
        ],
    }
    searches, calls = [], []

    async def search(query, /, *, volatility):
        searches.append((query.corp_code, query.group, volatility))
        return [SimpleNamespace(filing_number=NUMBER, report_title="Semi-Annual Report (2026.06)")]

    async def fetch(service, /, *, volatility, **params):
        calls.append((service, params["fiscal_year"], params["report_period"]))
        rows = filed.get((service, params["report_period"]))
        return None if rows is None else SimpleNamespace(list=rows)

    read = read_debt_maturities(search_filings=search, fetch_service=fetch, today=WINDOW.start)
    subject = CalendarSubject("00126380", "Example Co.", korean_name="예시")
    found = await read(subject, WINDOW)
    assert isinstance(found, DebtMaturities)
    assert [(i.date, i.details["issuer"]) for i in found.items] == [
        (dt.date(2026, 12, 4), "자회사")
    ]
    assert (found.period, found.bonds) == (PeriodRef(2026, "H1"), None)
    assert searches == [("00126380", "A", "high")]
    assert ("det_scrits_isu_acmslt", "2025", "11011") in calls
