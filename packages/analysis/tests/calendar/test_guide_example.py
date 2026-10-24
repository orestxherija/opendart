"""The calendar guide's example, without the SDK or MCP.

``or_none``, ``sdk_filing_search``, ``sdk_filing_pages``, ``sdk_fetch_service``, and
``calendar_report`` match docs/data-access.md, docs/filings.md, docs/extracts.md, and
docs/calendar.md. A duck-typed client stands in for ``opendart.OpenDART``, and a local
``NoDataError`` for the SDK's exception of that name.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.calendar import (
    CalendarSubject,
    calendar_kinds,
    calendar_window,
    corporate_action_calendar,
    read_debt_maturities,
)
from opendart_analysis.catalog import service
from tests.support.events import HYNIX, SAMSUNG, buyback, convertible_bond, filing

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from opendart_analysis.filings import FilingPage, FilingPageQuery, ReadFilingPage
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
BOND = "20260915000123"


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


async def or_none[T](call: Awaitable[T]) -> T | None:
    try:
        return await call
    except NoDataError:
        return None


def sdk_filing_search(client: Any) -> SearchFilings:
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


def sdk_filing_pages(client: Any) -> ReadFilingPage:
    async def read_filing_page(
        query: FilingPageQuery, /, *, volatility: Volatility
    ) -> FilingPage | None:
        del volatility  # This recipe caches nothing.
        return await or_none(
            client.disclosures.search(
                corporation_code=query.corp_code,
                filing_start_date=f"{query.start:%Y%m%d}",
                filing_end_date=f"{query.end:%Y%m%d}",
                final_reports_only="Y" if query.final_only else None,
                disclosure_category=query.group,
                disclosure_subcategory=query.subtype,
                corporation_type=query.corporation_type,
                page_number=query.page,
                page_size=query.page_size,
            )
        )

    return read_filing_page


def sdk_fetch_service(client: Any) -> FetchService:
    async def fetch_service(
        name: str, /, *, volatility: Volatility, **params: str | None
    ) -> object | None:
        del volatility  # This recipe caches nothing.
        spec = service(name)
        method = getattr(getattr(client, spec.resource), spec.name)
        return await or_none(method(**params))

    return fetch_service


async def calendar_report(client: Any, today: dt.date) -> list[str]:
    printed: list[str] = []
    companies = [
        CalendarSubject("00126380", "SAMSUNG ELECTRONICS CO,.LTD", korean_name="삼성전자"),
        CalendarSubject("00164779", "SK hynix Inc.", korean_name="에스케이하이닉스"),
    ]
    window = calendar_window("90d", include_past=None, today=today)
    selection = calendar_kinds(None)  # Every kind with dates, and debt maturities.
    fetch = sdk_fetch_service(client)
    maturities = read_debt_maturities(
        search_filings=sdk_filing_search(client), fetch_service=fetch, today=today
    )
    calendar = await corporate_action_calendar(
        companies,
        window=window,
        kinds=selection.events,
        maturities=maturities if selection.debt else None,
        fetch_service=fetch,
        read_filing_page=sdk_filing_pages(client),
        today=today,
    )
    names = {company.corp_code: company.name for company in companies}
    printed.extend(
        f"{item.date} {names[item.corp_code]} {item.action} {item.filing_number} {dict(item.details)}"
        for item in calendar.items
    )
    for company in calendar.companies:
        debt = company.maturities
        if debt is not None and debt.bonds is not None:
            printed.append(
                f"{company.subject.name} {debt.bonds.due_within_1y} {debt.bonds.outstanding}"
            )
        if company.failed or company.error:
            printed.append(f"{company.subject.name} {company.failed} {company.error}")
    return printed


def search_row(body: dict[str, str]) -> SimpleNamespace:
    """Convert a wire-format search record to the SDK's field names."""
    return SimpleNamespace(
        filing_number=body["rcept_no"],
        report_title=body["report_nm"],
        corporation_code=body["corp_code"],
    )


class FakeDisclosures:
    """Answers ``disclosures.search``: periodic reports (A) and major issues (B) per company."""

    def __init__(self) -> None:
        self.filed = {
            (SAMSUNG[0], "A"): [filing(HALF_YEAR, "Semi-Annual Report (2026.06)")],
            (SAMSUNG[0], "B"): [filing(BOND, "Decision on Issuance of Convertible Bonds")],
            (HYNIX[0], "B"): [
                filing("20261019000305", "Decision on Acquisition of Treasury Stock", HYNIX)
            ],
        }

    async def search(self, **params: Any) -> SimpleNamespace:
        rows = self.filed.get((params["corporation_code"], params["disclosure_category"]))
        if not rows:
            raise NoDataError
        return SimpleNamespace(
            list=[search_row(r) for r in rows], total_count=len(rows), total_page=1
        )


class FakeServices:
    """Answers services with rows filed per (method, company, report period)."""

    def __init__(self, filed: dict[tuple[str, str, str | None], list[Any]]) -> None:
        self.filed = filed
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., Awaitable[SimpleNamespace]]:
        async def method(**params: Any) -> SimpleNamespace:
            self.calls.append(name)
            key = (name, params["corporation_code"], params.get("report_period"))
            if (rows := self.filed.get(key)) is None:
                raise NoDataError
            return SimpleNamespace(status="000", list=rows)

        return method


def issue(maturity: str, **fields: str) -> SimpleNamespace:
    record = {
        "filing_number": HALF_YEAR,
        "isu_cmpny": "삼성전자㈜",
        "scrits_knd_nm": "Corporate Bonds",
        "isu_mth_nm": "Public offering",
        "isu_de": "2025.12.29",
        "facvalu_totamt": "30,000,000,000",
        "intrt": "3.36",
        "evl_grad_instt": "AA-(한국기업평가)",
        "mtd": maturity,
        "repy_at": "미상환",
    }
    return SimpleNamespace(**(record | fields))


def client() -> SimpleNamespace:
    major = FakeServices(
        {
            ("cvbd_is_decsn", SAMSUNG[0], None): [convertible_bond(BOND)],
            ("tsstk_aq_decsn", HYNIX[0], None): [buyback()],
        }
    )
    periodic = FakeServices(
        {
            ("det_scrits_isu_acmslt", SAMSUNG[0], "11012"): [issue("2026.12.30")],
            ("cprnd_nrdmp_blce", SAMSUNG[0], "11012"): [
                SimpleNamespace(
                    filing_number=HALF_YEAR,
                    remndr_exprtn2="Total",
                    yy1_below="100,000,000,000",
                    yy2_excess_yy3_below="150,000,000,000",
                    sm="250,000,000,000",
                )
            ],
        }
    )
    return SimpleNamespace(
        disclosures=FakeDisclosures(), major_issues=major, periodic_reports=periodic
    )


async def test_the_example_prints_dated_actions_maturities_and_bond_totals():
    fake = client()
    lines = await calendar_report(fake, TODAY)
    assert lines == [
        "2026-11-12 SAMSUNG ELECTRONICS CO,.LTD subscription 20260915000123 {'event': 'Convertible bond', 'face_value': 30000000000, 'series': '3', 'coupon_pct': 1.5}",
        "2026-11-12 SAMSUNG ELECTRONICS CO,.LTD payment_date 20260915000123 {'event': 'Convertible bond', 'face_value': 30000000000, 'series': '3', 'coupon_pct': 1.5}",
        "2026-12-30 SAMSUNG ELECTRONICS CO,.LTD debt_maturity 20260814001234 {'event': 'Debt maturity', 'instrument': 'Corporate Bonds', 'face_value': 30000000000, 'coupon': 3.36, 'redeemed': 'no'}",
        "2027-01-20 SK hynix Inc. buyback_end 20261019000305 {'event': 'Treasury stock acquisition', 'shares': 175467, 'amount': 17002800000, 'method': '유가증권시장을 통한 장내 매수'}",
        "SAMSUNG ELECTRONICS CO,.LTD 100000000000 250000000000",
    ]
    assert "det_scrits_isu_acmslt" in fake.periodic_reports.calls


PROBE = """
import sys
import opendart_analysis.calendar
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp"}))
"""


def test_importing_the_calendar_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
