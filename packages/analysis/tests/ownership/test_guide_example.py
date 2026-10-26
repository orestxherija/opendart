"""The ownership guide's example, run through a duck-typed client without the SDK or MCP.

``sdk_holdings`` matches the ownership guide, ``sdk_periodic`` the capital guide, and
``sdk_filing_search`` the data-access guide; a local ``NoDataError`` stands in for the SDK's
exception of that name. The rows are a trimmed copy of Samsung Electronics' FY2025 annual report.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.ownership import holding_reports, ownership_report
from opendart_analysis.reports import resolve_period
from packages.analysis.tests.capital.records import ANNUAL, TODAY, Company, Row, share_row

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from opendart_analysis.ownership import HoldingQuery
    from opendart_analysis.reports import ReportQuery
    from opendart_analysis.upstream import FilingQuery, FilingRecord, SearchFilings, Volatility

pytestmark = pytest.mark.anyio


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


def holder(kind, name, relate, end, pct):
    return Row(
        filing_number=ANNUAL,
        stock_knd=kind,
        nm=name,
        relate=relate,
        trmend_posesn_stock_co=end,
        trmend_posesn_stock_qota_rt=pct,
        stlm_dt="2025-12-31",
    )


PERIODIC = {
    "hyslr_sttus": [
        holder("보통주", "삼성생명보험㈜", "최대주주 본인", "503,904,843", "8.51"),
        holder("보통주", "삼성물산㈜", "계열회사", "298,818,100", "5.05"),
        holder("보통주", "Total", None, "1,174,366,888", "19.84"),
    ],
    "stock_totqy_sttus": [
        share_row("보통주", *["-"] * 7, "5,919,637,922", "91,828,987", "5,827,808,935")
    ],
    "mrhl_sttus": [Row(shrholdr_co="4,195,927", hold_stock_rate="66.04%", filing_number=ANNUAL)],
}
ELESTOCK = [
    Row(
        filing_number="20261016000492",
        filing_date="2026-10-16",
        repror="이재용",
        isu_exctv_ofcps="회장",
        sp_stock_lmp_irds_cnt="7,667,100",
    ),
    Row(filing_number="20240102000001", filing_date="2024-01-02", repror="Earlier"),
]


class FakeClient:
    """Answers the filing search, periodic reports, and holding reports like the SDK."""

    def __init__(self) -> None:
        self.disclosures = SimpleNamespace(search=self.search)
        names = ("hyslr_sttus", "stock_totqy_sttus", "hyslr_chg_sttus", "mrhl_sttus")
        self.periodic_reports = SimpleNamespace(**{name: self.periodic(name) for name in names})
        self.equity_disclosures = SimpleNamespace(
            majorstock=self.holdings([]), elestock=self.holdings(ELESTOCK)
        )

    async def search(self, **params: Any) -> SimpleNamespace:
        del params
        filing = SimpleNamespace(filing_number=ANNUAL, report_title="Annual Report (2025.12)")
        return SimpleNamespace(list=[filing])

    def periodic(self, name: str) -> Callable[..., Awaitable[SimpleNamespace]]:
        async def call(
            *, corporation_code: str, fiscal_year: str, report_period: str
        ) -> SimpleNamespace:
            del corporation_code
            rows = PERIODIC.get(name)
            if (fiscal_year, report_period) != ("2025", "11011") or rows is None:
                raise NoDataError
            return SimpleNamespace(list=rows)

        return call

    def holdings(self, rows: list[Row]) -> Callable[..., Awaitable[SimpleNamespace]]:
        async def call(*, corporation_code: str) -> SimpleNamespace:
            del corporation_code
            if not rows:
                raise NoDataError
            return SimpleNamespace(list=rows)

        return call


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


def sdk_holdings(method: Callable[..., Awaitable[Any]]):
    async def fetch(query: HoldingQuery, /, *, volatility: Volatility) -> Sequence[Any] | None:
        del volatility  # This recipe caches nothing.
        response = await or_none(method(corporation_code=query.corp_code))
        return None if response is None else response.list

    return fetch


async def test_the_guide_reads_control_and_holding_reports_through_the_client():
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
    report = await ownership_report(
        samsung,
        resolved,
        fetch_largest_holders=sdk_periodic(reports.hyslr_sttus),
        fetch_share_counts=sdk_periodic(reports.stock_totqy_sttus),
        fetch_control_changes=sdk_periodic(reports.hyslr_chg_sttus),
        fetch_minority_holders=sdk_periodic(reports.mrhl_sttus),
        today=TODAY,
    )
    assert report is not None
    snapshot = report.snapshot
    assert (report.ref.label, snapshot.largest_shareholder, snapshot.controlling_pct) == (
        "FY2025",
        "삼성생명보험㈜",
        19.84,
    )
    assert (snapshot.share_class, snapshot.free_float_estimate_pct) == ("common", 78.61)
    assert [(h.name, h.relation) for h in snapshot.holders] == [
        ("삼성생명보험㈜", "largest shareholder"),
        ("삼성물산㈜", "affiliate"),
    ]
    assert snapshot.minority is not None
    assert snapshot.minority.share_pct == 66.04
    assert report.control_changes == ()
    activity = await holding_reports(
        samsung.corp_code,
        since=TODAY - timedelta(days=180),
        fetch_major_holdings=sdk_holdings(client.equity_disclosures.majorstock),
        fetch_insider_holdings=sdk_holdings(client.equity_disclosures.elestock),
        today=TODAY,
    )
    assert [(r.reporter, r.position, r.change) for r in activity.insider] == [
        ("이재용", "회장", 7_667_100)
    ]
    assert (activity.insider_activity.reports, activity.insider_activity.increases) == (1, 1)
    assert activity.major == ()
