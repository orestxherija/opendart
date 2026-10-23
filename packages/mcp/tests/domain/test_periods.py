"""Reporting periods, periodic titles, and latest-period candidates."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_mcp.domain.periods import (
    FILING_DEADLINE_DAYS,
    FIRST_FISCAL_YEAR,
    FIRST_INDICATOR_YEAR,
    PERIODS_BY_REPORT_CODE,
    PERIOD_LABELS,
    REPORT_CODES,
    PeriodRef,
    PeriodicTitle,
    filing_deadline,
    fiscal_years_back,
    latest_candidates,
    parse_periodic_title,
    period_end,
    period_from_title,
)


def labels(refs: tuple[PeriodRef, ...]) -> list[str]:
    return [ref.label for ref in refs]


def test_report_code_tables():
    assert dict(REPORT_CODES) == {"FY": "11011", "H1": "11012", "Q1": "11013", "Q3": "11014"}
    assert {code: PERIODS_BY_REPORT_CODE[code] for code in REPORT_CODES.values()} == {
        "11011": "FY",
        "11012": "H1",
        "11013": "Q1",
        "11014": "Q3",
    }
    assert set(PERIOD_LABELS) == set(REPORT_CODES) == set(FILING_DEADLINE_DAYS)
    assert (FIRST_FISCAL_YEAR, FIRST_INDICATOR_YEAR) == (2015, 2022)


def test_period_ref_properties():
    assert PeriodRef(2025, "FY").label == "FY2025"
    assert PeriodRef(2025, "Q3").label == "Q3 2025"
    assert PeriodRef(2026, "H1").report_code == "11012"
    assert PeriodRef(2025, "Q1", end_date=date(2025, 3, 31)) == PeriodRef(2025, "Q1")
    assert hash(PeriodRef(2025, "Q1", end_date=date(2025, 3, 31))) == hash(PeriodRef(2025, "Q1"))
    assert PeriodRef(2025, "Q1") != PeriodRef(2025, "Q3")


@pytest.mark.parametrize(
    ("fye_month", "period", "expected"),
    [
        (12, "FY", date(2025, 12, 31)),
        (12, "Q3", date(2025, 9, 30)),
        (12, "H1", date(2025, 6, 30)),
        (12, "Q1", date(2025, 3, 31)),
        (3, "FY", date(2025, 3, 31)),
        (3, "Q3", date(2024, 12, 31)),
        (3, "H1", date(2024, 9, 30)),
        (3, "Q1", date(2024, 6, 30)),
        (6, "Q3", date(2025, 3, 31)),
        (2, "FY", date(2025, 2, 28)),
    ],
)
def test_period_end(fye_month, period, expected):
    assert period_end(2025, period, fye_month=fye_month) == expected


@pytest.mark.parametrize("fye_month", [0, 13, -1])
def test_invalid_year_end_months_are_rejected(fye_month):
    with pytest.raises(ValueError, match="fye_month must be between 1 and 12"):
        period_end(2025, "FY", fye_month=fye_month)
    with pytest.raises(ValueError, match="fye_month"):
        period_from_title(PeriodicTitle("annual", 2025, 12, None), fye_month=fye_month)
    with pytest.raises(ValueError, match="fye_month"):
        latest_candidates(
            today=date(2026, 1, 1), period="latest", fiscal_year=None, fye_month=fye_month
        )


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("FY", date(2026, 3, 31)),
        ("Q3", date(2025, 11, 14)),
        ("H1", date(2025, 8, 14)),
        ("Q1", date(2025, 5, 15)),
    ],
)
def test_filing_deadline(period, expected):
    assert filing_deadline(2025, period) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Annual Report (2025.12)", PeriodicTitle("annual", 2025, 12, None)),
        ("Semi-Annual Report (2026.06)", PeriodicTitle("semiannual", 2026, 6, None)),
        ("Quarterly Report (2026.03)", PeriodicTitle("quarterly", 2026, 3, None)),
        ("  Annual   Report   (2025.12)  ", PeriodicTitle("annual", 2025, 12, None)),
        ("annual report(2025.12)", PeriodicTitle("annual", 2025, 12, None)),
        ("Business Report (2025.12)", PeriodicTitle("annual", 2025, 12, None)),
        ("Half-Year Report (2025.06)", PeriodicTitle("semiannual", 2025, 6, None)),
        ("Semiannual Report (2025.06)", PeriodicTitle("semiannual", 2025, 6, None)),
        ("Semi Annual Report (2025.06)", PeriodicTitle("semiannual", 2025, 6, None)),
        ("Quarter Report (2025.9)", PeriodicTitle("quarterly", 2025, 9, None)),
        ("Annual Report (2025-12)", PeriodicTitle("annual", 2025, 12, None)),
        ("사업보고서 (2025.12)", PeriodicTitle("annual", 2025, 12, None)),
        ("반기보고서 (2025.06)", PeriodicTitle("semiannual", 2025, 6, None)),
        ("분기보고서 (2025.09)", PeriodicTitle("quarterly", 2025, 9, None)),
        (
            "[Revision of statements] Annual Report (2025.12)",
            PeriodicTitle("annual", 2025, 12, "Revision of statements"),
        ),
        (
            "[Corrected attachment][Added attachment]Quarterly Report (2026.03)",
            PeriodicTitle("quarterly", 2026, 3, "Corrected attachment"),
        ),
        (
            "[기재정정]사업보고서 (2025.12)",
            PeriodicTitle("annual", 2025, 12, "Revision of statements"),
        ),
    ],
)
def test_parse_periodic_title(title, expected):
    assert parse_periodic_title(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Report on Major Issues",
        "Annual Report",
        "Annual Report (2025.13)",
        "Annual Report (2025.00)",
        "Audit Report (2025.12)",
        "Notice of delayed submission of Annual Report (2025.12)",
        "Annual Report (2025.12) supplement",
        "",
    ],
)
def test_other_titles_are_not_periodic(title):
    assert parse_periodic_title(title) is None


@pytest.mark.parametrize(
    ("kind", "year", "month", "expected"),
    [
        ("annual", 2025, 12, [("FY2025", date(2025, 12, 31))]),
        ("semiannual", 2026, 6, [("H1 2026", date(2026, 6, 30))]),
        ("quarterly", 2026, 3, [("Q1 2026", date(2026, 3, 31))]),
        ("quarterly", 2025, 9, [("Q3 2025", date(2025, 9, 30))]),
    ],
)
def test_period_from_title_with_december_year_end(kind, year, month, expected):
    refs = period_from_title(PeriodicTitle(kind, year, month, None))
    assert [(ref.label, ref.end_date) for ref in refs] == expected


@pytest.mark.parametrize(
    ("kind", "month", "expected"),
    [
        ("annual", 3, [("FY2025", date(2025, 3, 31)), ("FY2024", date(2025, 3, 31))]),
        ("quarterly", 6, [("Q1 2026", date(2025, 6, 30)), ("Q1 2025", date(2025, 6, 30))]),
        ("semiannual", 9, [("H1 2026", date(2025, 9, 30)), ("H1 2025", date(2025, 9, 30))]),
        ("quarterly", 12, [("Q3 2026", date(2025, 12, 31)), ("Q3 2025", date(2025, 12, 31))]),
    ],
)
def test_period_from_title_with_march_year_end_returns_both_labels(kind, month, expected):
    refs = period_from_title(PeriodicTitle(kind, 2025, month, None), fye_month=3)
    assert [(ref.label, ref.end_date) for ref in refs] == expected


@pytest.mark.parametrize(
    ("kind", "month", "fye_month"),
    [
        ("quarterly", 12, 12),
        ("annual", 6, 12),
        ("semiannual", 3, 12),
        ("annual", 11, 12),
        ("quarterly", 9, 3),
    ],
)
def test_period_from_title_rejects_inconsistent_titles(kind, month, fye_month):
    assert period_from_title(PeriodicTitle(kind, 2025, month, None), fye_month=fye_month) == ()


def test_latest_candidates_put_the_open_filing_window_first():
    refs = latest_candidates(today=date(2026, 10, 22), period="latest", fiscal_year=None)
    assert labels(refs) == ["Q3 2026", "H1 2026", "Q1 2026", "FY2025", "Q3 2025", "H1 2025"]
    assert refs[0].end_date == date(2026, 9, 30)


@pytest.mark.parametrize(
    ("today", "first"),
    [
        (date(2026, 3, 15), "FY2025"),
        (date(2026, 4, 1), "Q1 2026"),
        (date(2026, 10, 1), "Q3 2026"),
        (date(2026, 9, 30), "H1 2026"),
        (date(2026, 1, 1), "FY2025"),
        (date(2025, 12, 31), "Q3 2025"),
    ],
)
def test_latest_candidates_start_with_the_last_ended_period(today, first):
    refs = latest_candidates(today=today, period="latest", fiscal_year=None)
    assert refs[0].label == first


def test_latest_candidates_for_one_period_kind():
    refs = latest_candidates(today=date(2026, 2, 1), period="FY", fiscal_year=None)
    assert labels(refs) == ["FY2025", "FY2024", "FY2023", "FY2022", "FY2021", "FY2020"]
    q3 = latest_candidates(today=date(2026, 10, 22), period="Q3", fiscal_year=None, depth=3)
    assert labels(q3) == ["Q3 2026", "Q3 2025", "Q3 2024"]


def test_latest_candidates_for_one_fiscal_year():
    refs = latest_candidates(today=date(2026, 10, 22), period="latest", fiscal_year=2024)
    assert labels(refs) == ["FY2024", "Q3 2024", "H1 2024", "Q1 2024"]
    assert latest_candidates(today=date(2026, 10, 22), period="latest", fiscal_year=2030) == ()
    assert latest_candidates(today=date(2026, 10, 22), period="FY", fiscal_year=2026) == ()


def test_latest_candidates_stop_at_the_first_fiscal_year():
    refs = latest_candidates(today=date(2015, 5, 20), period="latest", fiscal_year=None)
    assert labels(refs) == ["Q1 2015"]
    assert latest_candidates(today=date(2015, 3, 1), period="latest", fiscal_year=None) == ()


def test_latest_candidates_with_march_year_end_list_both_labels():
    refs = latest_candidates(
        today=date(2026, 10, 22), period="latest", fiscal_year=None, fye_month=3
    )
    assert labels(refs) == ["H1 2027", "H1 2026", "Q1 2027", "Q1 2026", "FY2026", "FY2025"]
    assert refs[0].end_date == refs[1].end_date == date(2026, 9, 30)
    one = latest_candidates(
        today=date(2026, 10, 22), period="latest", fiscal_year=None, fye_month=3, depth=1
    )
    assert labels(one) == ["H1 2027"]


def test_fiscal_years_back():
    ref = PeriodRef(2025, "FY", end_date=date(2025, 12, 31))
    assert labels(fiscal_years_back(ref, 3)) == ["FY2025", "FY2024", "FY2023"]
    every_third = fiscal_years_back(ref, 3, step=3)
    assert labels(every_third) == ["FY2025", "FY2022", "FY2019"]
    assert [item.end_date for item in every_third] == [
        date(2025, 12, 31),
        date(2022, 12, 31),
        date(2019, 12, 31),
    ]
    assert labels(fiscal_years_back(PeriodRef(2016, "Q3"), 5)) == ["Q3 2016", "Q3 2015"]
    assert fiscal_years_back(PeriodRef(2016, "Q3"), 2)[1].end_date is None


def test_fiscal_years_back_keeps_month_ends():
    ref = PeriodRef(2024, "FY", end_date=date(2024, 2, 29))
    assert [item.end_date for item in fiscal_years_back(ref, 2)] == [
        date(2024, 2, 29),
        date(2023, 2, 28),
    ]


@pytest.mark.parametrize(("years", "step"), [(0, 1), (1, 0), (-1, 1)])
def test_fiscal_years_back_rejects_bad_arguments(years, step):
    with pytest.raises(ValueError, match="years and step must be at least 1"):
        fiscal_years_back(PeriodRef(2025, "FY"), years, step=step)
