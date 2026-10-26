"""The debt guide's example, without the SDK or MCP.

``or_none``, ``sdk_filing_search``, ``sdk_fetch_service``, and ``debt_report`` match the
data-access, extracts, and debt guides. A duck-typed client stands in for ``opendart.OpenDART``,
and a local ``NoDataError`` for the SDK's exception of that name.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.catalog import service
from opendart_analysis.debt import debt_profile, maturity_schedule
from opendart_analysis.domain.dates import DateWindow
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
HALF_YEAR = "20260814001234"


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


class FakeDisclosures:
    """Answers ``disclosures.search`` with one half-year report."""

    async def search(self, **params: Any) -> SimpleNamespace:
        del params
        row = SimpleNamespace(filing_number=HALF_YEAR, report_title="Semi-Annual Report (2026.06)")
        return SimpleNamespace(list=[row])


class FakePeriodicReports:
    """Answers periodic-report services with the rows filed for their period."""

    def __init__(self, filed: dict[tuple[str, str, str], list[SimpleNamespace]]) -> None:
        self.filed = filed
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., Awaitable[SimpleNamespace]]:
        async def method(**params: Any) -> SimpleNamespace:
            self.calls.append((name, params))
            rows = self.filed.get((name, params["fiscal_year"], params["report_period"]))
            if rows is None:
                raise NoDataError
            return SimpleNamespace(status="000", list=rows)

        return method


class FakeClient:
    """The only parts of the SDK client the guide uses."""

    def __init__(self, filed: dict[tuple[str, str, str], list[SimpleNamespace]]) -> None:
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


async def debt_report(client: FakeClient) -> list[str]:
    printed: list[str] = []
    samsung = Company(corp_code="00126380", fye_month=12)
    names = ("삼성전자", "SAMSUNG ELECTRONICS CO,.LTD")
    today = TODAY
    resolved = await resolve_period(
        samsung,
        period="latest",
        fiscal_year=None,
        search_filings=sdk_filing_search(client),
        today=today,
    )
    fetch = sdk_fetch_service(client)
    profile = await debt_profile(samsung, resolved, names=names, fetch_service=fetch, today=today)
    schedule = await maturity_schedule(
        samsung,
        resolved,
        window=DateWindow(today, today + timedelta(days=365)),
        names=names,
        fetch_service=fetch,
        today=today,
    )
    if profile is None:
        return ["No debt-security tables in the latest report"]
    for ladder in profile.ladder:
        buckets = [(bucket.maturity_bucket, bucket.amount) for bucket in ladder.buckets]
        printed.append(f"{ladder.instrument} {ladder.total} {buckets}")
    printed.append(f"{profile.ref.label} {profile.figures}")
    printed.extend(
        f"{issue.maturity} {issue.security} {issue.amount} {issue.coupon} {issue.rating}"
        for issue in profile.issues
        if issue.redeemed != "yes"
    )
    printed.extend(
        f"{maturity.date} {maturity.instrument} {maturity.face_value} {maturity.filing_number}"
        for maturity in schedule.maturities
    )
    printed.append(str([source.filing_number for source in profile.sources]))
    return printed


def issue(maturity: str, **fields: str) -> SimpleNamespace:
    record = {
        "filing_number": HALF_YEAR,
        "isu_cmpny": "삼성전자㈜",
        "scrits_knd_nm": "Corporate Bonds",
        "isu_mth_nm": "Public offering",
        "isu_de": "2026.02.21",
        "facvalu_totamt": "150,000,000,000",
        "intrt": "3.36",
        "evl_grad_instt": "AA-(한국기업평가)",
        "mtd": maturity,
        "repy_at": "미상환",
    }
    return SimpleNamespace(**(record | fields))


FILED = {
    ("cprnd_nrdmp_blce", "2026", "11012"): [
        SimpleNamespace(
            filing_number=HALF_YEAR,
            remndr_exprtn2="Total",
            yy1_below="100,000,000,000",
            yy2_excess_yy3_below="150,000,000,000",
            sm="250,000,000,000",
        )
    ],
    ("det_scrits_isu_acmslt", "2026", "11012"): [
        issue("2029.02.21"),
        issue("2027.04.04", scrits_knd_nm="Commercial Paper", facvalu_totamt="20,000,000,000"),
        issue("2026.04.04", repy_at="상환"),
    ],
}


async def test_the_example_prints_the_ladder_open_issues_and_maturities():
    client = FakeClient(FILED)
    assert await debt_report(client) == [
        "corporate_bonds 250000000000 [('<=1y', 100000000000), ('2-3y', 150000000000)]",
        "H1 2026 DebtFigures(total_debt_securities=250000000000, due_within_1y=100000000000, due_within_1y_pct=40.0)",
        "2027-04-04 Commercial Paper 20000000000 3.36 AA-",
        "2029-02-21 Corporate Bonds 150000000000 3.36 AA-",
        f"2027-04-04 Commercial Paper 20000000000 {HALF_YEAR}",
        f"['{HALF_YEAR}']",
    ]
    profile_calls = [name for name, _ in client.periodic_reports.calls][:6]
    assert profile_calls[0] == "cprnd_nrdmp_blce"
    assert profile_calls[-1] == "det_scrits_isu_acmslt"


async def test_a_report_without_debt_tables_has_no_profile():
    assert await debt_report(FakeClient({})) == ["No debt-security tables in the latest report"]


PROBE = """
import sys
import opendart_analysis.debt
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "pydantic"}))
"""


def test_importing_debt_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
