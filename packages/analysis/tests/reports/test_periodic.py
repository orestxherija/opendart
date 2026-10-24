"""Finding the latest periodic report and the periods to probe, from synthetic filings."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest

from opendart_analysis.errors import MissingDataError
from opendart_analysis.reports import (
    PROBE_ATTEMPTS,
    PeriodRef,
    PeriodUnavailableError,
    first_available,
    latest_periodic_report,
    period_volatility,
    resolve_period,
)
from opendart_analysis.upstream import FilingQuery

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


@dataclass(frozen=True)
class Filing:
    filing_number: str | None
    report_title: str | None


DECEMBER = Company("00126380", 12)
MARCH = Company("00126380", 3)


class Search:
    """A filing search that answers every query with the same records and records the calls."""

    def __init__(self, *filings: Filing, empty: bool = False) -> None:
        self.filings = None if empty else filings
        self.calls: list[tuple[FilingQuery, str]] = []

    async def __call__(self, query, /, *, volatility):
        self.calls.append((query, volatility))
        return self.filings


async def test_the_search_asks_for_fifteen_months_of_final_periodic_reports():
    search = Search()
    assert await latest_periodic_report(DECEMBER, search_filings=search, today=TODAY) is None
    assert search.calls == [
        (
            FilingQuery(
                "00126380", dt.date(2025, 7, 19), TODAY, group="A", final_only=True, limit=100
            ),
            "high",
        )
    ]


async def test_an_amended_older_report_does_not_become_latest():
    search = Search(
        Filing("20260915000111", "[Revision of statements]Annual Report (2025.12)"),
        Filing("20260814001234", "Semi-Annual Report (2026.06)"),
        Filing("20260515000456", "Quarterly Report (2026.03)"),
    )
    report = await latest_periodic_report(DECEMBER, search_filings=search, today=TODAY)
    assert report is not None
    assert (report.ref.period, report.ref.fiscal_year) == ("H1", 2026)
    assert (report.title, report.filed) == ("Semi-Annual Report (2026.06)", dt.date(2026, 8, 14))


async def test_the_latest_filing_of_one_period_is_its_final_version():
    search = Search(
        Filing("20260916000222", "[Revision of statements]Annual Report (2025.12)"),
        Filing("20260310000789", "Annual Report (2025.12)"),
        Filing("20260814001234", "Semi-Annual Report (2026.06)"),
    )
    report = await latest_periodic_report(DECEMBER, "FY", search_filings=search, today=TODAY)
    assert report is not None
    assert report.filing_number == "20260916000222"
    assert report.parsed.amendment == "Revision of statements"


async def test_records_without_a_title_or_number_and_misfit_titles_are_ignored():
    # A December year end has no quarterly report ending in December.
    search = Search(
        Filing(None, "Semi-Annual Report (2026.06)"),
        Filing("20260814001234", None),
        Filing("20260213000111", "Quarterly Report (2025.12)"),
        Filing("20260213000222", "Report on Major Issues"),
    )
    assert await latest_periodic_report(DECEMBER, search_filings=search, today=TODAY) is None


async def test_periods_after_the_latest_report_are_not_probed():
    search = Search(Filing("20260814001234", "Semi-Annual Report (2026.06)"))
    resolved = await resolve_period(
        DECEMBER, period="latest", fiscal_year=None, search_filings=search, today=TODAY
    )
    labels = [ref.label for ref in resolved.candidates]
    assert labels[0] == "H1 2026"
    assert "Q3 2026" not in labels
    assert labels[1:3] == ["Q1 2026", "FY2025"]
    assert resolved.report is not None
    assert resolved.note is None


async def test_both_labels_of_an_old_non_december_report_are_probed_first():
    # A late filer's newest report predates every deadline-based candidate.
    search = Search(Filing("20260213000111", "Quarterly Report (2025.12)"))
    resolved = await resolve_period(
        MARCH, period="latest", fiscal_year=None, search_filings=search, today=TODAY
    )
    assert [ref.label for ref in resolved.candidates] == ["Q3 2026", "Q3 2025"]
    assert {ref.end_date for ref in resolved.candidates} == {dt.date(2025, 12, 31)}


async def test_without_a_report_candidates_come_from_deadlines_with_a_note():
    search = Search(empty=True)
    resolved = await resolve_period(
        DECEMBER, period="latest", fiscal_year=None, search_filings=search, today=TODAY
    )
    assert resolved.report is None
    assert [ref.label for ref in resolved.candidates[:3]] == ["Q3 2026", "H1 2026", "Q1 2026"]
    assert resolved.note == (
        "No periodic report was found in the last 15 months; periods were chosen by filing deadlines."
    )


async def test_a_fiscal_year_skips_the_filing_search():
    search = Search(Filing("20260814001234", "Semi-Annual Report (2026.06)"))
    resolved = await resolve_period(
        DECEMBER, period="FY", fiscal_year=2024, search_filings=search, today=TODAY
    )
    assert search.calls == []
    assert [ref.label for ref in resolved.candidates] == ["FY2024"]
    assert (resolved.report, resolved.note) == (None, None)


@pytest.mark.parametrize(
    ("period", "fiscal_year", "wanted"),
    [("FY", 2030, "FY 2030"), ("Q1", 2014, "Q1 2014"), ("latest", None, "latest")],
)
async def test_an_impossible_period_raises_a_structured_error(period, fiscal_year, wanted):
    search = Search(empty=True)
    today = dt.date(2015, 1, 5) if fiscal_year is None else TODAY
    with pytest.raises(PeriodUnavailableError) as raised:
        await resolve_period(
            DECEMBER, period=period, fiscal_year=fiscal_year, search_filings=search, today=today
        )
    error = raised.value
    assert isinstance(error, MissingDataError)
    assert (error.period, error.fiscal_year, error.first_fiscal_year) == (period, fiscal_year, 2015)
    assert str(error) == (
        f"No {wanted} period is available: it has not ended yet or predates 2015, when OpenDART's periodic data begins."
    )


async def test_first_available_probes_in_order_up_to_the_attempt_limit():
    search = Search(empty=True)
    resolved = await resolve_period(
        DECEMBER, period="latest", fiscal_year=None, search_filings=search, today=TODAY
    )
    probed: list[str] = []

    async def fetch(ref: PeriodRef) -> str | None:
        probed.append(ref.label)
        return "rows" if ref.label == "H1 2026" else None

    assert await first_available(resolved, fetch) == (PeriodRef(2026, "H1"), "rows")
    assert probed == ["Q3 2026", "H1 2026"]

    async def nothing(ref: PeriodRef) -> str | None:
        probed.append(ref.label)

    probed.clear()
    assert await first_available(resolved, nothing) is None
    assert probed == [ref.label for ref in resolved.candidates[:PROBE_ATTEMPTS]]


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (PeriodRef(2026, "H1"), "low"),
        (PeriodRef(2026, "Q1"), "low"),
        (PeriodRef(2025, "FY"), "low"),
        (PeriodRef(2026, "Q3"), "high"),
    ],
)
def test_recent_periods_are_volatile(ref, expected):
    assert period_volatility(ref, fye_month=12, today=TODAY) == expected


def test_volatility_settles_two_weeks_after_the_deadline():
    q3 = PeriodRef(2025, "Q3")  # Due 2025-11-14.
    assert period_volatility(q3, fye_month=12, today=dt.date(2025, 11, 28)) == "high"
    assert period_volatility(q3, fye_month=12, today=dt.date(2025, 11, 29)) == "low"


def test_a_start_year_label_is_dated_by_its_period_end():
    # Q1 of the year ending June 2027 ended 2026-09-30 and is due 2026-11-14.
    start_label = PeriodRef(2026, "Q1", end_date=dt.date(2026, 9, 30))
    assert period_volatility(start_label, fye_month=6, today=TODAY) == "high"
    assert period_volatility(PeriodRef(2026, "Q1"), fye_month=6, today=TODAY) == "low"


@pytest.mark.parametrize(
    ("changes", "match"),
    [({"end": dt.date(2026, 1, 1)}, "before start"), ({"limit": 0}, "between 1 and 100")],
)
def test_filing_queries_reject_windows_and_limits_opendart_cannot_serve(changes, match):
    fields = {"corp_code": "00126380", "start": dt.date(2026, 2, 1), "end": TODAY} | changes
    with pytest.raises(ValueError, match=match):
        FilingQuery(**fields)
