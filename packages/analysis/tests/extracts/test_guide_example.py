"""The extracts guide's SDK recipe and dividend example, without the SDK or MCP.

``or_none``, ``sdk_filing_search``, ``sdk_fetch_service``, and ``latest_dividends`` match
docs/data-access.md and docs/extracts.md. A duck-typed client stands in for
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

from opendart_analysis.catalog import service
from opendart_analysis.extracts import (
    checked,
    fetch_records,
    filed_text,
    probe_attempts,
    sources,
    text,
)
from opendart_analysis.reports import first_available, resolve_period

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


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


class FakeDisclosures:
    """Answers ``disclosures.search`` with one annual report."""

    async def search(self, **params: Any) -> SimpleNamespace:
        del params
        row = SimpleNamespace(filing_number=ANNUAL, report_title="Annual Report (2025.12)")
        return SimpleNamespace(list=[row])


class FakePeriodicReports:
    """Answers ``periodic_reports.alot_matter`` for the periods that have data."""

    def __init__(self, filed: dict[tuple[str, str], list[SimpleNamespace]]) -> None:
        self.filed = filed
        self.calls: list[dict[str, Any]] = []

    async def alot_matter(self, **params: Any) -> SimpleNamespace:
        self.calls.append(params)
        rows = self.filed.get((params["fiscal_year"], params["report_period"]))
        if rows is None:
            raise NoDataError
        return SimpleNamespace(status="000", list=rows)


class FakeClient:
    """The only parts of the SDK client the guide uses."""

    def __init__(self, filed: dict[tuple[str, str], list[SimpleNamespace]]) -> None:
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


SAMSUNG = Company(corp_code="00126380", fye_month=12)


async def latest_dividends(client: FakeClient) -> list[str]:
    printed: list[str] = []
    resolved = await resolve_period(
        SAMSUNG,
        period="FY",
        fiscal_year=None,
        search_filings=sdk_filing_search(client),
        today=TODAY,
    )
    fetch = sdk_fetch_service(client)
    found = await first_available(
        resolved,
        lambda ref: fetch_records(
            "alot_matter", company=SAMSUNG, ref=ref, fetch_service=fetch, today=TODAY
        ),
        attempts=probe_attempts(resolved),
    )
    if found is None:
        return [f"No dividend table in {checked(resolved)}"]
    ref, rows = found
    for row in rows:
        label, kind = filed_text(text(row, "se")), filed_text(text(row, "stock_knd"))
        printed.append(f"{ref.label} {label} {kind} {text(row, "thstrm")}")
    numbers = (text(row, "filing_number") for row in rows)
    printed.append(str([source.filing_number for source in sources(numbers, resolved.report)]))
    return printed


def dividend(label: str, kind: str, current: str) -> SimpleNamespace:
    return SimpleNamespace(filing_number=ANNUAL, se=label, stock_knd=kind, thstrm=current)


async def test_the_recipe_reads_the_filed_annual_dividend_table():
    rows = [
        dividend("Cash dividend per share (KRW)", "보통주", "1,446"),
        dividend("Payout ratio (%)", "-", "29.2"),
    ]
    client = FakeClient({("2025", "11011"): rows})
    assert await latest_dividends(client) == [
        "FY2025 Cash dividend per share (KRW) 보통주 1,446",
        "FY2025 Payout ratio (%) None 29.2",
        f"['{ANNUAL}']",
    ]
    assert client.periodic_reports.calls == [
        {"corporation_code": "00126380", "fiscal_year": "2025", "report_period": "11011"}
    ]


async def test_a_filed_report_without_the_table_probes_only_its_period():
    client = FakeClient({("2024", "11011"): [dividend("x", "보통주", "1")]})
    assert await latest_dividends(client) == ['No dividend table in "Annual Report (2025.12)"']
    assert [call["fiscal_year"] for call in client.periodic_reports.calls] == ["2025"]


PROBE = """
import sys
import opendart_analysis.extracts
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "pydantic"}))
"""


def test_importing_extracts_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
