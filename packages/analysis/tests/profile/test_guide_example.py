"""The company-profile guide's example, without the SDK or MCP.

``or_none``, ``sdk_filing_search``, and ``print_profile`` match docs/data-access.md and
docs/profile.md. A duck-typed client stands in for ``opendart.OpenDART``, and a local
``NoDataError`` for the SDK's exception of that name.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from opendart_analysis.profile import (
    NO_OVERVIEW,
    NO_REPORT,
    fiscal_year_end_month,
    profile_company,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from opendart_analysis.upstream import FilingQuery, FilingRecord, SearchFilings, Volatility

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
ANNUAL = "20260310002820"


class NoDataError(Exception):
    """Stands in for ``opendart.NoDataError`` (OpenDART status 013)."""


class FakeDisclosures:
    """Answers ``disclosures.company`` and ``disclosures.search``."""

    def __init__(self, overview: SimpleNamespace | None, filings: list[SimpleNamespace]) -> None:
        self.overview = overview
        self.filings = filings
        self.searches: list[dict[str, Any]] = []

    async def company(self, **params: Any) -> SimpleNamespace:
        assert params == {"corporation_code": "00126380"}
        if self.overview is None:
            raise NoDataError
        return self.overview

    async def search(self, **params: Any) -> SimpleNamespace:
        self.searches.append(params)
        if not self.filings:
            raise NoDataError
        return SimpleNamespace(list=self.filings)


class FakeClient:
    """The only parts of the SDK client the guide uses."""

    def __init__(self, overview: SimpleNamespace | None, filings: list[SimpleNamespace]) -> None:
        self.disclosures = FakeDisclosures(overview, filings)


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


async def print_profile(client: FakeClient) -> list[object]:
    printed: list[object] = []
    overview = await or_none(client.disclosures.company(corporation_code="00126380"))
    samsung = Company("00126380", fiscal_year_end_month(overview))
    profile = await profile_company(
        samsung,
        overview,
        search_filings=sdk_filing_search(client),
        today=TODAY,
    )
    printed.append(
        (profile.facts.ceo, profile.facts.established, profile.facts.fiscal_year_end_month)
    )
    report = profile.latest_report
    printed.append(report.title if report else profile.notes)
    return printed


OVERVIEW = SimpleNamespace(
    stock_name="삼성전자",
    ceo_nm="  전영현 ",
    induty_code="264",
    est_dt="19690113",
    adres="경기도 수원시 영통구 삼성로 129 (매탄동)",
    hm_url="www.samsung.com/sec",
    ir_url="",
    phn_no="02-2255-0114",
    fax_no="-",
    jurir_no="1301110006246",
    bizr_no="1248100998",
    acc_mt="03",
)


async def test_the_example_profiles_a_company_with_its_latest_report():
    filing = SimpleNamespace(filing_number=ANNUAL, report_title="Annual Report (2026.03)")
    client = FakeClient(OVERVIEW, [filing])
    assert await print_profile(client) == [
        ("전영현", dt.date(1969, 1, 13), 3),
        "Annual Report (2026.03)",
    ]
    (search,) = client.disclosures.searches
    assert (search["disclosure_category"], search["final_reports_only"]) == ("A", "Y")


async def test_without_an_overview_or_reports_the_notes_say_so():
    client = FakeClient(None, [])
    assert await print_profile(client) == [(None, None, 12), (NO_OVERVIEW, NO_REPORT)]


PROBE = """
import sys
import opendart_analysis.profile
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "pydantic"}))
"""


def test_importing_profile_loads_neither_the_sdk_nor_mcp():
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
