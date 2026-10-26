"""The capital guide's example, run through a duck-typed client without the SDK or MCP.

``sdk_periodic`` matches the capital guide and ``sdk_filing_search`` the data-access guide; a
local ``NoDataError`` stands in for the SDK's exception of that name.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.capital import capital_structure
from opendart_analysis.reports import resolve_period
from packages.analysis.tests.capital.records import (
    ANNUAL,
    TODAY,
    Company,
    Row,
    share_row,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from opendart_analysis.reports import ReportQuery
    from opendart_analysis.upstream import FilingQuery, FilingRecord, SearchFilings, Volatility

pytestmark = pytest.mark.anyio


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


TREASURY = Row(
    stock_knd="보통주",
    acqs_mth1="Total",
    acqs_mth2="Total",
    acqs_mth3="Total",
    bsis_qy="29,700,000",
    change_qy_acqs="118,314,495",
    change_qy_dsps="6,040,880",
    change_qy_incnr="50,144,628",
    trmend_qy="91,828,987",
)


class FakeClient:
    """Answers ``disclosures.search`` and two periodic-report services like the SDK."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.disclosures = SimpleNamespace(search=self.search)
        self.periodic_reports = SimpleNamespace(
            stock_totqy_sttus=self.method("stock_totqy_sttus", [share_row("보통주", *SHARES)]),
            tesstk_acqs_dsps_sttus=self.method("tesstk_acqs_dsps_sttus", [TREASURY]),
        )

    async def search(self, **params: Any) -> SimpleNamespace:
        del params
        filing = SimpleNamespace(filing_number=ANNUAL, report_title="Annual Report (2025.12)")
        return SimpleNamespace(list=[filing])

    def method(self, name: str, rows: list[Row]) -> Callable[..., Awaitable[SimpleNamespace]]:
        async def call(
            *, corporation_code: str, fiscal_year: str, report_period: str
        ) -> SimpleNamespace:
            del corporation_code
            self.calls.append((name, fiscal_year, report_period))
            if (fiscal_year, report_period) != ("2025", "11011"):
                raise NoDataError
            return SimpleNamespace(list=rows)

        return call


# Samsung Electronics' FY2025 common-share counts, as OpenDART returned them.
SHARES = ("20,000,000,000", "7,780,466,850", "1,860,828,928", "-", "1,860,828,928", "-", "-")
SHARES += ("5,919,637,922", "91,828,987", "5,827,808,935")


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


def sdk_periodic(method: Callable[..., Awaitable[Any]]):
    async def fetch(query: ReportQuery, /, *, volatility: Volatility) -> Sequence[Any] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(
            method(
                corporation_code=query.corp_code,
                fiscal_year=str(query.fiscal_year),
                report_period=query.report_code,
            )
        )
        return None if response is None else response.list

    return fetch


async def test_the_guide_reads_share_counts_and_treasury_stock_through_the_client():
    client = FakeClient()
    samsung = Company(corp_code="00126380", fye_month=12)
    reports = client.periodic_reports
    resolved = await resolve_period(
        samsung,
        period="latest",
        fiscal_year=None,
        search_filings=sdk_filing_search(client),
        today=TODAY,
    )
    structure = await capital_structure(
        samsung,
        resolved,
        sections=("shares", "treasury_stock"),
        fetch_share_counts=sdk_periodic(reports.stock_totqy_sttus),
        fetch_treasury_stock=sdk_periodic(reports.tesstk_acqs_dsps_sttus),
        today=TODAY,
    )
    assert structure is not None
    assert structure.ref.label == "FY2025"
    counts = structure.shares
    assert (counts.issued, counts.treasury, counts.outstanding) == (
        5_919_637_922,
        91_828_987,
        5_827_808_935,
    )
    assert structure.treasury_stock is not None
    (movement,) = structure.treasury_stock
    assert (movement.share_class, movement.acquired, movement.retired, movement.end) == (
        "common",
        118_314_495,
        50_144_628,
        91_828_987,
    )
    assert structure.capital_changes is None
    assert client.calls == [
        ("stock_totqy_sttus", "2025", "11011"),
        ("tesstk_acqs_dsps_sttus", "2025", "11011"),
    ]


PROBE = """
import sys
import opendart_analysis.capital
import opendart_analysis.ownership
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp"}))
"""


def test_importing_capital_and_ownership_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
