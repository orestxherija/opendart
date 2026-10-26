"""The governance workflow over a FetchService of canned responses: calls, probes, sections."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.extracts import FilingSource
from opendart_analysis.governance import SECTION_SERVICES, governance_facts
from opendart_analysis.reports import (
    PROBE_ATTEMPTS,
    PeriodRef,
    PeriodicReport,
    PeriodicTitle,
    ResolvedPeriod,
)

if TYPE_CHECKING:
    from opendart_analysis.upstream import Volatility

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
ANNUAL = "20260310002820"
TITLE = "Annual Report (2025.12)"
FY2025 = PeriodRef(2025, "FY", end_date=dt.date(2025, 12, 31))


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


SAMSUNG = Company("00126380", 12)


@dataclass
class Source:
    """A FetchService over canned responses by (service, fiscal year) that records calls."""

    responses: dict[tuple[str, str], object] = field(default_factory=dict)
    calls: list[tuple[str, Volatility, dict[str, Any]]] = field(default_factory=list)
    failure: Exception | None = None

    async def __call__(
        self, service: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        self.calls.append((service, volatility, params))
        if self.failure is not None and service == "outcmpny_drctr_nd_change_sttus":
            raise self.failure
        return self.responses.get((service, params["fiscal_year"] or ""))

    def services(self) -> list[str]:
        return [service for service, _, _ in self.calls]


def listed(*records: dict[str, str], number: str = ANNUAL) -> SimpleNamespace:
    return SimpleNamespace(list=[SimpleNamespace(filing_number=number, **r) for r in records])


def resolved(*refs: PeriodRef, report: bool = True) -> ResolvedPeriod:
    filed = PeriodicReport(
        FY2025, PeriodicTitle("annual", 2025, 12, None), ANNUAL, TITLE, dt.date(2026, 3, 10)
    )
    return ResolvedPeriod(refs or (FY2025,), filed if report else None, None)


BOARD = listed({"drctr_co": "7", "otcmp_drctr_co": "3"})


async def test_only_the_requested_sections_are_fetched_for_the_period():
    source = Source({("outcmpny_drctr_nd_change_sttus", "2025"): BOARD})
    facts = await governance_facts(
        SAMSUNG, resolved(), sections=("board", "board"), fetch_service=source, today=TODAY
    )
    assert facts is not None
    assert (facts.ref, facts.sections) == (FY2025, ("board",))
    assert facts.board is not None
    assert facts.board.outside_director_pct == 42.9
    assert (facts.audit, facts.executives, facts.compensation, facts.employees) == (
        None,
        None,
        None,
        None,
    )
    assert facts.flags == ()
    assert facts.sources == (FilingSource(ANNUAL, TITLE),)
    assert source.calls == [
        (
            "outcmpny_drctr_nd_change_sttus",
            "low",
            {"corporation_code": "00126380", "fiscal_year": "2025", "report_period": "11011"},
        )
    ]


async def test_compensation_prefers_version_two_and_falls_back_per_service():
    group = SimpleNamespace(group=[SimpleNamespace(nm="갑", mendng_totamt="900,000,000")])
    source = Source(
        {
            ("hmv_audit_indvdl_by_sttus_v2", "2025"): group,
            ("indvdl_by_pay_v2", "2025"): SimpleNamespace(group=[]),
            ("indvdl_by_pay", "2025"): listed({"nm": "을", "mendng_totamt": "1,200,000,000"}),
        }
    )
    facts = await governance_facts(
        SAMSUNG, resolved(), sections=("compensation",), fetch_service=source, today=TODAY
    )
    assert facts is not None
    assert facts.compensation is not None
    assert [p.name for p in facts.compensation.directors_over_500m] == ["갑"]
    assert [p.name for p in facts.compensation.top_paid] == ["을"]
    assert source.services() == [
        *SECTION_SERVICES["compensation"],
        "hmv_audit_indvdl_by_sttus_v2",
        "indvdl_by_pay_v2",
        "indvdl_by_pay",
    ]
    assert facts.flags == ()


async def test_without_tables_every_candidate_is_probed_and_nothing_is_found():
    refs = (PeriodRef(2026, "H1"), PeriodRef(2026, "Q1"), FY2025, PeriodRef(2025, "Q3"))
    source = Source()
    facts = await governance_facts(
        SAMSUNG,
        resolved(*refs, report=False),
        sections=("executives",),
        fetch_service=source,
        today=TODAY,
    )
    assert facts is None
    assert [params["fiscal_year"] for _, _, params in source.calls] == ["2026", "2026", "2025"]
    assert len(source.calls) == PROBE_ATTEMPTS


async def test_unnamed_executives_leave_the_section_empty():
    source = Source({("exctv_sttus", "2025"): listed({"nm": "-"}, {"nm": " "})})
    facts = await governance_facts(
        SAMSUNG, resolved(), sections=("executives",), fetch_service=source, today=TODAY
    )
    assert facts is not None
    assert facts.executives is None


async def test_a_listed_prior_auditor_needs_no_extra_call():
    opinions = listed(
        {"fiscal_year": "제57기(당기)", "adtor": "가나회계법인", "adt_opinion": "적정의견"},
        {"fiscal_year": "제56기(전기)", "adtor": "가나회계법인", "adt_opinion": "적정의견"},
    )
    source = Source({("accnut_adtor_nm_nd_adt_opinion", "2025"): opinions})
    facts = await governance_facts(
        SAMSUNG, resolved(), sections=("audit",), fetch_service=source, today=TODAY
    )
    assert facts is not None
    assert facts.audit is not None
    assert (facts.audit.prior_auditor, facts.audit.auditor_changed_vs_prior_year) == (
        "가나회계법인",
        False,
    )
    assert facts.flags == ()
    assert source.services() == list(SECTION_SERVICES["audit"])


async def test_the_prior_auditor_is_not_looked_up_before_fiscal_2015():
    fy2015 = PeriodRef(2015, "FY", end_date=dt.date(2015, 12, 31))
    opinions = listed({"fiscal_year": "2015", "adtor": "가나회계법인", "adt_opinion": "적정"})
    source = Source({("accnut_adtor_nm_nd_adt_opinion", "2015"): opinions})
    facts = await governance_facts(
        SAMSUNG,
        resolved(fy2015, report=False),
        sections=("audit",),
        fetch_service=source,
        today=TODAY,
    )
    assert facts is not None
    assert facts.audit is not None
    assert facts.audit.prior_auditor is None
    assert len(source.calls) == len(SECTION_SERVICES["audit"])
    assert facts.sources == (FilingSource(ANNUAL),)


async def test_a_source_failure_reaches_the_caller_after_every_call():
    failure = RuntimeError("quota exhausted")
    source = Source(failure=failure)
    with pytest.raises(RuntimeError) as raised:
        await governance_facts(
            SAMSUNG,
            resolved(),
            sections=("audit", "board", "employees"),
            fetch_service=source,
            today=TODAY,
        )
    assert raised.value is failure
    assert len(source.calls) == 5


@pytest.mark.parametrize("sections", [(), ("pay",)])
async def test_sections_must_be_named_and_known(sections):
    with pytest.raises(ValueError, match="sections must name 1 to 5"):
        await governance_facts(
            SAMSUNG, resolved(), sections=sections, fetch_service=Source(), today=TODAY
        )
