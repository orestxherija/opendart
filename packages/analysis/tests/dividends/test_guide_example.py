"""The dividends guide's example, without the SDK or MCP.

``or_none``, ``sdk_filing_search``, ``sdk_fetch_service``, and ``cash_dividends`` match
docs/data-access.md, docs/extracts.md, and docs/dividends.md. A duck-typed client stands in
for ``opendart.OpenDART``, and a local ``NoDataError`` for the SDK's exception of that name.
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
from opendart_analysis.dividends import YIELD_NOTE, dividend_history
from opendart_analysis.extracts import checked
from opendart_analysis.reports import resolve_period

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

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
OLDER = "20230310000999"


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


class FakeDisclosures:
    """Answers ``disclosures.search`` with one annual report."""

    async def search(self, **params: Any) -> SimpleNamespace:
        del params
        row = SimpleNamespace(filing_number=ANNUAL, report_title="Annual Report (2025.12)")
        return SimpleNamespace(list=[row])


class FakePeriodicReports:
    """Answers ``periodic_reports.alot_matter`` for the fiscal years that have a table."""

    def __init__(self, filed: dict[str, list[SimpleNamespace]]) -> None:
        self.filed = filed
        self.calls: list[dict[str, Any]] = []

    async def alot_matter(self, **params: Any) -> SimpleNamespace:
        self.calls.append(params)
        rows = self.filed.get(params["fiscal_year"])
        if rows is None:
            raise NoDataError
        return SimpleNamespace(status="000", list=rows)


class FakeClient:
    """The only parts of the SDK client the guide uses."""

    def __init__(self, filed: dict[str, list[SimpleNamespace]]) -> None:
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


async def cash_dividends(client: FakeClient) -> list[object]:
    printed: list[object] = []
    samsung = Company(corp_code="00126380", fye_month=12)
    today = TODAY
    resolved = await resolve_period(
        samsung,
        period="FY",
        fiscal_year=None,
        search_filings=sdk_filing_search(client),
        today=today,
    )
    history = await dividend_history(
        samsung,
        resolved,
        years=5,
        fetch_service=sdk_fetch_service(client),
        today=today,
    )
    if history is None:
        printed.append(("No dividend table in", checked(resolved)))
        return printed
    printed.extend(
        (row.share_class, row.unit, row.values) for row in history.rows if row.measure == "cash_dps"
    )
    printed.append(([source.filing_number for source in history.sources], history.notes))
    return printed


def dividend(label: str, kind: str, values: tuple[str, str, str], number: str) -> SimpleNamespace:
    current, prior, older = values
    return SimpleNamespace(
        filing_number=number, se=label, stock_knd=kind, thstrm=current, frmtrm=prior, lwfr=older
    )


def table(number: str) -> list[SimpleNamespace]:
    return [
        dividend("Cash dividend per share (KRW)", "보통주", ("1,668", "1,446", "1,444"), number),
        dividend("Cash dividend per share (KRW)", "우선주", ("1,669", "1,447", "1,445"), number),
        dividend("Cash dividend rate of return (%)", "보통주", ("1.50", "2.70", "1.90"), number),
    ]


async def test_five_years_chain_the_annual_report_three_years_earlier():
    client = FakeClient({"2025": table(ANNUAL), "2022": table(OLDER)})
    assert await cash_dividends(client) == [
        ("common", "KRW/share", {2025: 1668, 2024: 1446, 2023: 1444, 2022: 1668, 2021: 1446}),
        ("preferred", "KRW/share", {2025: 1669, 2024: 1447, 2023: 1445, 2022: 1669, 2021: 1447}),
        ([ANNUAL, OLDER], (YIELD_NOTE,)),
    ]
    assert client.periodic_reports.calls == [
        {"corporation_code": "00126380", "fiscal_year": "2025", "report_period": "11011"},
        {"corporation_code": "00126380", "fiscal_year": "2022", "report_period": "11011"},
    ]


async def test_a_filed_report_without_the_table_has_no_history():
    client = FakeClient({})
    assert await cash_dividends(client) == [("No dividend table in", '"Annual Report (2025.12)"')]


PROBE = """
import sys
import opendart_analysis.dividends
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "pydantic"}))
"""


def test_importing_dividends_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
