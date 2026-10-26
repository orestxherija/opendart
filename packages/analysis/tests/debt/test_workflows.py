"""Debt workflows over a fake FetchService: periods probed, calls, provenance, and failures."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from opendart_analysis.debt import DEBT_SERVICES, debt_profile, maturity_schedule, prior_annual
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.domain.periods import PeriodRef
from opendart_analysis.reports import resolve_period

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.reports import ResolvedPeriod
    from opendart_analysis.upstream import FilingQuery, FilingRecord, Volatility

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
HALF_YEAR = "20260814001234"
ANNUAL = "20260310002820"
NAMES = ("한빛화학", "HANBIT CHEMICAL CO., LTD.")
WINDOW = DateWindow(dt.date(2026, 10, 22), dt.date(2027, 12, 31))


class Company:
    corp_code = "00126380"
    fye_month = 12


class UnavailableError(Exception):
    """A data-access failure that analysis must not catch."""


class Source:
    """Answers services with the rows filed for (service, fiscal year, report code)."""

    def __init__(self, filed: dict[tuple[str, str, str], list[SimpleNamespace]]) -> None:
        self.filed = filed
        self.calls: list[tuple[str, str | None, str | None, Volatility]] = []
        self.failing: str | None = None

    async def __call__(
        self, service: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        self.calls.append((service, params["fiscal_year"], params["report_period"], volatility))
        assert params["corporation_code"] == "00126380"
        if service == self.failing:
            raise UnavailableError(service)
        rows = self.filed.get((service, str(params["fiscal_year"]), str(params["report_period"])))
        return None if rows is None else SimpleNamespace(list=rows)

    def periods(self, service: str) -> list[tuple[str | None, str | None]]:
        return [(year, code) for name, year, code, _ in self.calls if name == service]


def search(*titles: tuple[str, str]):
    async def search_filings(
        query: FilingQuery, /, *, volatility: Volatility
    ) -> Sequence[FilingRecord] | None:
        del query, volatility
        rows = [SimpleNamespace(filing_number=n, report_title=t) for n, t in titles]
        return rows or None

    return search_filings


async def latest(*titles: tuple[str, str]) -> ResolvedPeriod:
    return await resolve_period(
        Company(), period="latest", fiscal_year=None, search_filings=search(*titles), today=TODAY
    )


def issue(number: str, maturity: str, **fields: str) -> SimpleNamespace:
    record = {
        "filing_number": number,
        "isu_cmpny": "한빛화학㈜",
        "scrits_knd_nm": "Corporate Bonds",
        "isu_mth_nm": "Public offering",
        "isu_de": "2025.05.02",
        "facvalu_totamt": "100,000,000,000",
        "intrt": "3.10",
        "mtd": maturity,
        "repy_at": "미상환",
    }
    return SimpleNamespace(**(record | fields))


def balance(number: str, within: str, total: str) -> SimpleNamespace:
    return SimpleNamespace(filing_number=number, remndr_exprtn2="Total", yy1_below=within, sm=total)


async def test_the_profile_reads_six_tables_of_the_filed_report_with_provenance():
    source = Source(
        {
            ("cprnd_nrdmp_blce", "2026", "11012"): [balance(HALF_YEAR, "70", "120")],
            ("det_scrits_isu_acmslt", "2026", "11012"): [
                issue(HALF_YEAR, "2027.05.02", repy_at="상환"),
                issue(ANNUAL, "2026.12.15", isu_cmpny="Hanbit Q"),
            ],
        }
    )
    resolved = await latest((HALF_YEAR, "Semi-Annual Report (2026.06)"))
    profile = await debt_profile(
        Company(), resolved, names=NAMES, fetch_service=source, today=TODAY
    )
    assert profile is not None
    assert profile.ref == PeriodRef(2026, "H1")
    assert [service for service, *_ in source.calls] == list(DEBT_SERVICES)
    assert {volatility for *_, volatility in source.calls} == {"low"}
    (bonds,) = profile.ladder
    assert (bonds.instrument, bonds.total) == ("corporate_bonds", 120)
    assert (profile.figures.due_within_1y, profile.figures.due_within_1y_pct) == (70, 58.3)
    assert [(item.maturity, item.redeemed, item.other_issuer) for item in profile.issues] == [
        (dt.date(2026, 12, 15), "no", "Hanbit Q"),
        (dt.date(2027, 5, 2), "yes", None),
    ]
    assert [(s.filing_number, s.title) for s in profile.sources] == [
        (HALF_YEAR, "Semi-Annual Report (2026.06)"),
        (ANNUAL, None),
    ]


async def test_candidates_are_probed_until_one_has_any_table():
    source = Source({("det_scrits_isu_acmslt", "2026", "11012"): [issue(HALF_YEAR, "2027.01.01")]})
    resolved = await latest()
    profile = await debt_profile(
        Company(), resolved, names=NAMES, fetch_service=source, today=TODAY
    )
    assert profile is not None
    assert (profile.ref, profile.ladder, profile.figures.total_debt_securities) == (
        PeriodRef(2026, "H1"),
        (),
        None,
    )
    assert source.periods("cprnd_nrdmp_blce") == [("2026", "11014"), ("2026", "11012")]


async def test_a_filed_report_without_tables_is_no_profile_after_one_period():
    source = Source({})
    resolved = await latest((ANNUAL, "Annual Report (2025.12)"))
    assert (
        await debt_profile(Company(), resolved, names=NAMES, fetch_service=source, today=TODAY)
        is None
    )
    assert len(source.calls) == len(DEBT_SERVICES)


async def test_data_access_failures_propagate_unchanged():
    source = Source({})
    source.failing = "new_capl_scrits_nrdmp_blce"
    resolved = await latest((HALF_YEAR, "Semi-Annual Report (2026.06)"))
    with pytest.raises(UnavailableError):
        await debt_profile(Company(), resolved, names=NAMES, fetch_service=source, today=TODAY)
    with pytest.raises(UnavailableError):
        source.failing = "det_scrits_isu_acmslt"
        await maturity_schedule(
            Company(), resolved, window=WINDOW, names=NAMES, fetch_service=source, today=TODAY
        )


async def test_the_schedule_adds_the_prior_annual_issuance_record():
    source = Source(
        {
            ("det_scrits_isu_acmslt", "2026", "11012"): [
                issue(HALF_YEAR, "2026.12.15", scrits_knd_nm="Commercial Paper"),
                issue(HALF_YEAR, "2026.10.01"),
            ],
            ("det_scrits_isu_acmslt", "2025", "11011"): [
                issue(ANNUAL, "2027.05.02", repy_at="일부상환"),
                issue(ANNUAL, "2026.12.15", scrits_knd_nm="Commercial Paper"),
            ],
            ("cprnd_nrdmp_blce", "2026", "11012"): [balance(HALF_YEAR, "70", "120")],
        }
    )
    resolved = await latest((HALF_YEAR, "Semi-Annual Report (2026.06)"))
    schedule = await maturity_schedule(
        Company(), resolved, window=WINDOW, names=NAMES, fetch_service=source, today=TODAY
    )
    assert [(m.date, m.instrument, m.redeemed, m.filing_number) for m in schedule.maturities] == [
        (dt.date(2026, 12, 15), "Commercial Paper", "no", HALF_YEAR),
        (dt.date(2027, 5, 2), "Corporate Bonds", "partly", ANNUAL),
    ]
    assert schedule.period == PeriodRef(2026, "H1")
    assert schedule.bonds is not None
    assert schedule.bonds.total == 120
    assert sorted(source.periods("det_scrits_isu_acmslt")) == [("2025", "11011"), ("2026", "11012")]


async def test_without_tables_in_any_candidate_the_prior_annual_report_is_latest():
    source = Source(
        {
            ("det_scrits_isu_acmslt", "2025", "11011"): [
                issue(ANNUAL, "2026.12.01", scrits_knd_nm="CP")
            ]
        }
    )
    resolved = await latest((HALF_YEAR, "Semi-Annual Report (2026.06)"))
    schedule = await maturity_schedule(
        Company(), resolved, window=WINDOW, names=NAMES, fetch_service=source, today=TODAY
    )
    assert schedule.period == PeriodRef(2025, "FY")
    assert [m.instrument for m in schedule.maturities] == ["CP"]
    assert schedule.bonds is None
    assert source.periods("cprnd_nrdmp_blce") == [("2026", "11012"), ("2025", "11011")]


async def test_no_tables_anywhere_is_an_empty_schedule():
    resolved = await latest((ANNUAL, "Annual Report (2025.12)"))
    source = Source({})
    schedule = await maturity_schedule(
        Company(), resolved, window=WINDOW, names=NAMES, fetch_service=source, today=TODAY
    )
    assert (schedule.maturities, schedule.period, schedule.bonds) == ((), None, None)
    assert source.periods("det_scrits_isu_acmslt") == [("2025", "11011")]


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (PeriodRef(2026, "Q3"), PeriodRef(2025, "FY")),
        (PeriodRef(2026, "FY"), None),
        (PeriodRef(2015, "H1"), None),
    ],
)
def test_prior_annual_reports(ref, expected):
    assert prior_annual(ref) == expected
