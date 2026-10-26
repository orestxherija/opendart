"""The financials guide's example, run through a duck-typed client without the SDK or MCP.

``sdk_major_accounts`` matches the financials guide and ``sdk_filing_search`` the data-access
guide; a local ``NoDataError`` stands in for the SDK's exception of that name.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.financials import HistoryRequest, major_accounts
from opendart_analysis.reports import resolve_period
from packages.analysis.tests.financials.records import HALF, TODAY, Company, T, won

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from opendart_analysis.financials import FetchMajorAccounts, MajorAccountRecord, ReportQuery
    from opendart_analysis.upstream import FilingQuery, FilingRecord, SearchFilings, Volatility

pytestmark = pytest.mark.anyio


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


def account(statement: str, name: str, current: float, cumulative: float | None = None):
    return SimpleNamespace(
        statement_scope="CFS",
        statement_type=statement,
        account_name=name,
        current_period_amount=won(current),
        prior_period_amount=None,
        two_periods_prior_amount=None,
        current_period_cumulative_amount=won(cumulative),
        prior_period_cumulative_amount=None,
        filing_number=HALF,
        currency="KRW",
    )


class FakeClient:
    """Answers ``disclosures.search`` and ``fnltt_singl_acnt`` like the SDK."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.disclosures = SimpleNamespace(search=self.search)
        self.financial_statements = SimpleNamespace(fnltt_singl_acnt=self.fnltt_singl_acnt)

    async def search(self, **params: Any) -> SimpleNamespace:
        del params
        filing = SimpleNamespace(filing_number=HALF, report_title="Semi-Annual Report (2026.06)")
        return SimpleNamespace(list=[filing])

    async def fnltt_singl_acnt(
        self, *, corporation_code: str, fiscal_year: str, report_period: str
    ) -> SimpleNamespace:
        del corporation_code
        self.calls.append((fiscal_year, report_period))
        if (fiscal_year, report_period) != ("2026", "11012"):
            raise NoDataError
        rows = [account("IS", "Revenue", 170, 300), account("IS", "Operating income", 90, 145)]
        return SimpleNamespace(list=rows)


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


def sdk_major_accounts(client: FakeClient) -> FetchMajorAccounts:
    async def fetch_major_accounts(
        query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[MajorAccountRecord] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(
            client.financial_statements.fnltt_singl_acnt(
                corporation_code=query.corp_code,
                fiscal_year=str(query.fiscal_year),
                report_period=query.report_code,
            )
        )
        return None if response is None else response.list

    return fetch_major_accounts


async def test_the_guide_reads_the_latest_major_accounts_through_the_client():
    client = FakeClient()
    samsung = Company(corp_code="00126380", fye_month=12)
    resolved = await resolve_period(
        samsung,
        period="latest",
        fiscal_year=None,
        search_filings=sdk_filing_search(client),
        today=TODAY,
    )
    history = await major_accounts(
        samsung,
        resolved,
        request=HistoryRequest(years=2),
        fetch_major_accounts=sdk_major_accounts(client),
        today=TODAY,
    )
    assert client.calls == [("2026", "11012"), ("2025", "11012")]
    assert history is not None
    assert history.ref.label == "H1 2026"
    revenue = min(history.report.lines, key=lambda line: line.rank)
    assert (revenue.values.get(history.ref), revenue.cumulative.get(history.ref)) == (
        170 * T,
        300 * T,
    )
    assert history.derived == {"operating_margin": 48.33}
    assert history.notes == ("No data for H1 2025; earlier columns are missing.",)


PROBE = """
import sys
import opendart_analysis.financials
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp"}))
"""


def test_importing_financials_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
