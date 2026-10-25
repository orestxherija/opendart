"""The package guide's data-access recipe and reports example, without the SDK or MCP.

``or_none`` and ``sdk_filing_search`` match docs/data-access.md. A duck-typed client stands in for
``opendart.OpenDART``, and a local ``NoDataError`` for the SDK's exception of that name.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.errors import (
    AnalysisError,
    DataSourceError,
    MissingDataError,
    NotConfiguredError,
)
from opendart_analysis.reports import first_available, resolve_period

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from opendart_analysis.upstream import FilingQuery, FilingRecord, SearchFilings, Volatility

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


class FakeDisclosures:
    """Answers ``disclosures.search`` like the SDK: a response with ``list``, or no data."""

    def __init__(self, titles: dict[str, str]) -> None:
        self.titles = titles
        self.calls: list[dict[str, Any]] = []

    async def search(self, **params: Any) -> SimpleNamespace:
        self.calls.append(params)
        if not self.titles:
            raise NoDataError
        rows = [
            SimpleNamespace(filing_number=number, report_title=title, corporation_name="Example")
            for number, title in self.titles.items()
        ]
        return SimpleNamespace(status="000", list=rows)


class FakeFinancialStatements:
    """Answers ``financial_statements.fnltt_singl_acnt`` for the periods that have data."""

    def __init__(self, filed: set[tuple[str, str]]) -> None:
        self.filed = filed
        self.calls: list[tuple[str, str]] = []

    async def fnltt_singl_acnt(
        self, *, corporation_code: str, fiscal_year: str, report_period: str
    ) -> SimpleNamespace:
        del corporation_code
        self.calls.append((fiscal_year, report_period))
        if (fiscal_year, report_period) not in self.filed:
            raise NoDataError
        return SimpleNamespace(list=[SimpleNamespace(account_name="Revenue")])


class FakeClient:
    """The only parts of the SDK client the guide uses."""

    def __init__(self, titles: dict[str, str], filed: set[tuple[str, str]]) -> None:
        self.disclosures = FakeDisclosures(titles)
        self.financial_statements = FakeFinancialStatements(filed)


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


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


SAMSUNG = Company(corp_code="00126380", fye_month=12)


async def probe_latest(client: FakeClient):
    resolved = await resolve_period(
        SAMSUNG,
        period="latest",
        fiscal_year=None,
        search_filings=sdk_filing_search(client),
        today=TODAY,
    )
    found = await first_available(
        resolved,
        lambda ref: or_none(
            client.financial_statements.fnltt_singl_acnt(
                corporation_code=SAMSUNG.corp_code,
                fiscal_year=str(ref.fiscal_year),
                report_period=ref.report_code,
            )
        ),
    )
    return resolved, found


async def test_the_recipe_resolves_and_probes_through_the_client():
    client = FakeClient({"20260814001234": "Semi-Annual Report (2026.06)"}, {("2026", "11012")})
    resolved, found = await probe_latest(client)
    assert client.disclosures.calls == [
        {
            "corporation_code": "00126380",
            "filing_start_date": "20250719",
            "filing_end_date": "20261022",
            "disclosure_category": "A",
            "final_reports_only": "Y",
            "page_size": 100,
        }
    ]
    assert resolved.report is not None
    assert resolved.report.title == "Semi-Annual Report (2026.06)"
    assert found is not None
    ref, accounts = found
    assert (ref.label, accounts.list[0].account_name) == ("H1 2026", "Revenue")
    assert client.financial_statements.calls == [("2026", "11012")]


async def test_no_data_from_the_client_falls_back_to_deadlines():
    client = FakeClient({}, {("2026", "11014")})
    resolved, found = await probe_latest(client)
    assert resolved.report is None
    assert resolved.note is not None
    assert found is not None
    assert found[0].label == "Q3 2026"


async def test_other_client_failures_reach_the_caller_unchanged():
    class QuotaError(Exception):
        pass

    client = FakeClient({}, set())

    async def failing(**params: Any) -> SimpleNamespace:
        raise QuotaError

    client.disclosures.search = failing
    with pytest.raises(QuotaError):
        await probe_latest(client)


def test_failure_categories_stay_distinct_and_carry_their_details():
    upstream = DataSourceError("OpenDART did not respond.", operation="disclosures.search")
    missing = NotConfiguredError("No filing search was supplied.", dependency="search_filings")
    assert upstream.operation == "disclosures.search"
    assert missing.dependency == "search_filings"
    categories = (MissingDataError, DataSourceError, NotConfiguredError)
    assert all(issubclass(category, AnalysisError) for category in categories)
    assert not any(issubclass(a, b) for a in categories for b in categories if a is not b)


PROBE = """
import sys
import opendart_analysis.errors
import opendart_analysis.reports
import opendart_analysis.upstream
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "anyio", "pydantic"}))
"""


def test_importing_reports_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
