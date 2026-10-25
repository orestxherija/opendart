"""Fetching periodic-report extracts through a caller's FetchService, running fetches together,
choosing how many periods to probe, and describing provenance, from synthetic records."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import anyio
import pytest

from opendart_analysis.catalog import services
from opendart_analysis.errors import MissingDataError
from opendart_analysis.extracts import (
    PERIODIC_PARAMS,
    FilingSource,
    checked,
    fetch_records,
    fetch_response,
    gather_all,
    probe_attempts,
    sources,
)
from opendart_analysis.reports import (
    PROBE_ATTEMPTS,
    PeriodRef,
    PeriodicReport,
    PeriodicTitle,
    ResolvedPeriod,
)

if TYPE_CHECKING:
    from opendart_analysis.upstream import FetchService, Volatility

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
MARCH_END = dt.date(2026, 3, 31)
TITLE = "Annual Report (2026.03)"


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


DECEMBER = Company("00126380", 12)


@dataclass
class Source:
    """A FetchService over canned responses that records each call."""

    responses: dict[str, object | None] = field(default_factory=dict)
    calls: list[tuple[str, Volatility, dict[str, Any]]] = field(default_factory=list)

    async def __call__(
        self, service: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        self.calls.append((service, volatility, params))
        return self.responses.get(service)


def report(ref: PeriodRef) -> PeriodicReport:
    parsed = PeriodicTitle("annual", 2026, 3, None)
    return PeriodicReport(ref, parsed, "20260625000111", TITLE, dt.date(2026, 6, 25))


@pytest.mark.parametrize(
    ("ref", "volatility"),
    [
        # Q3 2026 is due on November 14, so its window is still open.
        (PeriodRef(2026, "Q3"), "high"),
        (PeriodRef(2026, "H1"), "low"),
        (PeriodRef(2024, "FY"), "low"),
    ],
)
async def test_a_fetch_names_the_period_and_its_volatility(ref, volatility):
    response = SimpleNamespace(list=[SimpleNamespace(se="x")])
    source = Source({"alot_matter": response})
    found = await fetch_response(
        "alot_matter", company=DECEMBER, ref=ref, fetch_service=source, today=TODAY
    )
    assert found is response
    assert source.calls == [
        (
            "alot_matter",
            volatility,
            {
                "corporation_code": "00126380",
                "fiscal_year": str(ref.fiscal_year),
                "report_period": ref.report_code,
            },
        )
    ]
    assert tuple(source.calls[0][2]) == PERIODIC_PARAMS


async def test_a_march_year_end_settles_by_its_own_deadline():
    # FY2026 of a March year end ends 2026-03-31 and was due 90 days later.
    ref = PeriodRef(2026, "FY", end_date=MARCH_END)
    source = Source()
    march = Company("00126380", 3)
    await fetch_response("alot_matter", company=march, ref=ref, fetch_service=source, today=TODAY)
    assert source.calls[0][1] == "low"


async def test_records_come_from_the_list_container_and_no_data_is_none():
    rows = [SimpleNamespace(se="a"), SimpleNamespace(se="b")]
    source = Source({"alot_matter": SimpleNamespace(list=rows), "empty": SimpleNamespace()})
    ref = PeriodRef(2025, "FY")

    async def fetch(service: str) -> list[object] | None:
        return await fetch_records(
            service, company=DECEMBER, ref=ref, fetch_service=source, today=TODAY
        )

    assert await fetch("alot_matter") == rows
    assert await fetch("empty") == []
    assert await fetch("missing") is None


async def test_a_source_failure_reaches_the_caller_unchanged():
    class QuotaError(Exception):
        pass

    error = QuotaError()

    async def failing(service: str, /, *, volatility: Volatility, **params: str | None) -> None:
        raise error

    fetch_service: FetchService = failing
    with pytest.raises(QuotaError) as raised:
        await fetch_records(
            "alot_matter",
            company=DECEMBER,
            ref=PeriodRef(2025, "FY"),
            fetch_service=fetch_service,
            today=TODAY,
        )
    assert raised.value is error


def test_every_periodic_report_service_takes_the_periodic_parameters():
    periodic = services("periodic_reports")
    assert len(periodic) == 30
    assert all(tuple(p.name for p in spec.params) == PERIODIC_PARAMS for spec in periodic)


async def answer[T](value: T, delay: float = 0) -> T:
    await anyio.sleep(delay)
    return value


async def test_gather_all_keeps_call_order():
    assert await gather_all([answer("slow", 0.02), answer("fast")]) == ["slow", "fast"]
    assert await gather_all(answer(n) for n in range(3)) == [0, 1, 2]
    assert await gather_all([]) == []


async def test_gather_all_finishes_every_call_then_raises_the_first_failure_unwrapped():
    finished: list[str] = []
    first = MissingDataError("No data for the first call.")

    async def fail(error: Exception, delay: float) -> str:
        await anyio.sleep(delay)
        raise error

    async def slow() -> str:
        await anyio.sleep(0.02)
        finished.append("slow")
        return "slow"

    with pytest.raises(MissingDataError) as raised:
        await gather_all([fail(first, 0.01), slow(), fail(ValueError("later"), 0)])
    assert raised.value is first
    assert finished == ["slow"]


def test_without_a_report_the_shared_probe_limit_applies():
    resolved = ResolvedPeriod((PeriodRef(2026, "H1"), PeriodRef(2026, "Q1")), None, "note")
    assert probe_attempts(resolved) == PROBE_ATTEMPTS
    assert checked(resolved) == "H1 2026, Q1 2026"


def test_a_december_report_is_read_under_its_one_label():
    ref = PeriodRef(2025, "FY", end_date=dt.date(2025, 12, 31))
    older = PeriodRef(2025, "Q3", end_date=dt.date(2025, 9, 30))
    assert probe_attempts(ResolvedPeriod((ref, older), report(ref), None)) == 1


def test_a_march_report_is_read_under_both_labels_of_its_period():
    ref = PeriodRef(2026, "FY", end_date=MARCH_END)
    start_label = PeriodRef(2025, "FY", end_date=MARCH_END)
    year_before = PeriodRef(2025, "FY", end_date=dt.date(2025, 3, 31))
    resolved = ResolvedPeriod((ref, start_label, year_before), report(ref), None)
    assert probe_attempts(resolved) == 2
    assert checked(resolved) == f'"{TITLE}"'


def test_a_report_without_an_end_date_is_read_once():
    ref = PeriodRef(2026, "FY")
    assert probe_attempts(ResolvedPeriod((ref, PeriodRef(2025, "FY")), report(ref), None)) == 1


def test_sources_skip_invalid_numbers_and_title_the_report():
    found = sources(
        [" 20260625000111 ", None, "", "bad", "20260625000111", "20250310000001"],
        report(PeriodRef(2026, "FY", end_date=MARCH_END)),
    )
    assert found == [FilingSource("20260625000111", TITLE), FilingSource("20250310000001")]
    assert sources(["20250310000001"]) == [FilingSource("20250310000001", None)]
