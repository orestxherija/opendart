"""The governance guide's example, through the SDK recipes, without the SDK or MCP.

``or_none``, ``sdk_filing_search``, ``sdk_fetch_service``, and ``main`` match the data-access,
extracts, and governance guides. A duck-typed client stands in for ``opendart.OpenDART``, and a
local ``NoDataError`` for the SDK's exception of that name.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.catalog import service
from opendart_analysis.extracts import checked
from opendart_analysis.governance import governance_facts
from opendart_analysis.reports import resolve_period

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from opendart_analysis.upstream import (
        FetchService,
        FilingQuery,
        FilingRecord,
        SearchFilings,
        Volatility,
    )

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
ANNUAL = "20260310002820"
PRIOR = "20250311001111"

type Filed = dict[tuple[str, str, str], SimpleNamespace]


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


class FakeDisclosures:
    """Answers ``disclosures.search`` with one annual report."""

    async def search(self, **params: Any) -> SimpleNamespace:
        del params
        row = SimpleNamespace(filing_number=ANNUAL, report_title="Annual Report (2025.12)")
        return SimpleNamespace(list=[row])


class FakePeriodicReports:
    """Answers any periodic-report method for the (method, year, report code) filed."""

    def __init__(self, filed: Filed) -> None:
        self.filed = filed
        self.calls: list[tuple[str, str]] = []

    def __getattr__(self, method: str) -> Callable[..., Awaitable[SimpleNamespace]]:
        async def call(**params: Any) -> SimpleNamespace:
            self.calls.append((method, params["fiscal_year"]))
            key = (method, params["fiscal_year"], params["report_period"])
            if key not in self.filed:
                raise NoDataError
            return self.filed[key]

        return call


class FakeClient:
    """The only parts of the SDK client the guide uses."""

    def __init__(self, filed: Filed) -> None:
        self.disclosures = FakeDisclosures()
        self.periodic_reports = FakePeriodicReports(filed)


async def or_none[T](call: Awaitable[T]) -> T | None:
    try:
        return await call
    except NoDataError:
        return None


def sdk_filing_search(client: FakeClient) -> SearchFilings:
    async def search_filings(
        query: FilingQuery, /, *, volatility: Volatility
    ) -> Sequence[FilingRecord] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(
            client.disclosures.search(
                corporation_code=query.corp_code,
                filing_start_date=f"{query.start:%Y%m%d}",
                filing_end_date=f"{query.end:%Y%m%d}",
                disclosure_category=query.group,
                final_reports_only="Y" if query.final_only else None,
                page_size=query.limit,
            )
        )
        return None if response is None else response.list

    return search_filings


def sdk_fetch_service(client: FakeClient) -> FetchService:
    async def fetch_service(
        name: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        del volatility  # This recipe caches nothing.
        spec = service(name)
        method = getattr(getattr(client, spec.resource), spec.name)
        return await or_none(method(**params))

    return fetch_service


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


async def main(client: FakeClient) -> list[str]:
    printed: list[str] = []
    samsung = Company(corp_code="00126380", fye_month=12)
    today = TODAY
    resolved = await resolve_period(
        samsung,
        period="FY",
        fiscal_year=None,
        search_filings=sdk_filing_search(client),
        today=today,
    )
    facts = await governance_facts(
        samsung,
        resolved,
        sections=("audit", "board", "compensation"),
        fetch_service=sdk_fetch_service(client),
        today=today,
    )
    if facts is None:
        return [f"No governance tables in {checked(resolved)}"]
    audit, board, pay = facts.audit, facts.board, facts.compensation
    if audit is not None:
        printed.append(f"{facts.ref.label} {audit.auditor} {audit.opinion} {audit.prior_auditor}")
    if board is not None:
        printed.append(f"{board.directors} {board.outside_directors} {board.outside_director_pct}")
    if pay is not None:
        printed.append(str([(person.name, person.total) for person in pay.top_paid]))
    printed.extend(f"{flag.kind} {flag.detail}" for flag in facts.flags)
    printed.append(str([source.filing_number for source in facts.sources]))
    return printed


def rows(*records: dict[str, str], number: str = ANNUAL) -> SimpleNamespace:
    return SimpleNamespace(list=[SimpleNamespace(filing_number=number, **r) for r in records])


def opinion(term: str, auditor: str, filed: str = "적정의견") -> dict[str, str]:
    return {"fiscal_year": term, "adtor": auditor, "adt_opinion": filed}


FILED: Filed = {
    ("accnut_adtor_nm_nd_adt_opinion", "2025", "11011"): rows(
        opinion("제57기(당기)", "가나회계법인", "한정의견")
    ),
    ("accnut_adtor_nm_nd_adt_opinion", "2024", "11011"): rows(
        opinion("제56기(당기)", "다라회계법인"), number=PRIOR
    ),
    ("outcmpny_drctr_nd_change_sttus", "2025", "11011"): rows(
        {"drctr_co": "9", "otcmp_drctr_co": "5", "apnt": "1", "rlsofc": "0", "mdstrm_resig": "0"}
    ),
    ("indvdl_by_pay_v2", "2025", "11011"): SimpleNamespace(
        group=[
            SimpleNamespace(nm="갑", ofcps="회장", mendng_totamt="2,500,000,000"),
            SimpleNamespace(nm="을", ofcps="사장", mendng_totamt="3,100,000,000"),
        ]
    ),
}


async def test_the_example_reads_audit_board_and_pay_with_flags():
    client = FakeClient(FILED)
    assert await main(client) == [
        "FY2025 가나회계법인 qualified 다라회계법인",
        "9 5 55.6",
        "[('을', 3100000000), ('갑', 2500000000)]",
        "modified_opinion Qualified opinion for FY2025, filed as 한정의견.",
        "auditor_change Auditor changed from 다라회계법인 to 가나회계법인.",
        f"['{ANNUAL}', '{PRIOR}']",
    ]
    calls = client.periodic_reports.calls
    # Three audit tables, the board, four pay totals, both Ver 2.0 services, one Ver 1.0
    # fallback, and last year's opinion table.
    assert len(calls) == 12
    assert calls[-1] == ("accnut_adtor_nm_nd_adt_opinion", "2024")
    assert ("indvdl_by_pay", "2025") not in calls
    assert ("hmv_audit_indvdl_by_sttus", "2025") in calls


async def test_a_report_without_the_tables_is_named():
    client = FakeClient({})
    assert await main(client) == ['No governance tables in "Annual Report (2025.12)"']


PROBE = """
import sys
import opendart_analysis.governance
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "pydantic"}))
"""


def test_importing_governance_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
