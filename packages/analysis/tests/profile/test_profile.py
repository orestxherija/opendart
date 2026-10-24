"""company_facts and profile_company: normalization, the latest report, provenance, notes."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from opendart_analysis.profile import (
    NO_REPORT,
    company_facts,
    fiscal_year_end_month,
    profile_company,
)
from opendart_analysis.reports import PeriodRef

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


def overview(**fields: str) -> SimpleNamespace:
    names = (
        "stock_name ceo_nm induty_code est_dt adres hm_url ir_url phn_no fax_no jurir_no bizr_no"
    )
    return SimpleNamespace(**{**dict.fromkeys(names.split()), **fields})


def test_facts_collapse_whitespace_and_drop_placeholders():
    facts = company_facts(
        overview(ceo_nm="Jun  Young-hyun", hm_url="", fax_no="-", est_dt="1969.01.13"), 12
    )
    assert facts.ceo == "Jun Young-hyun"
    assert (facts.website, facts.fax, facts.address) == (None, None, None)
    assert facts.established == dt.date(1969, 1, 13)
    assert facts.fiscal_year_end_month == 12


def test_without_an_overview_only_the_fiscal_year_end_month_is_known():
    facts = company_facts(None, 3)
    assert facts.fiscal_year_end_month == 3
    assert facts.stock_name is None


class Search:
    """A SearchFilings answering one page, recording each query and volatility."""

    def __init__(self, rows: list[SimpleNamespace] | None) -> None:
        self.rows = rows
        self.calls: list[tuple[object, str]] = []

    async def __call__(self, query: object, /, *, volatility: str) -> list[SimpleNamespace] | None:
        self.calls.append((query, volatility))
        return self.rows


async def test_the_latest_report_is_the_source_filing():
    rows = [
        SimpleNamespace(filing_number="20260814001234", report_title="반기보고서 (2026.06)"),
        SimpleNamespace(filing_number="20260310000789", report_title="사업보고서 (2025.12)"),
    ]
    search = Search(rows)
    profile = await profile_company(
        Company("00126380", 12), overview(), search_filings=search, today=TODAY
    )
    report = profile.latest_report
    assert report is not None
    assert report.ref == PeriodRef(2026, "H1", report.ref.end_date)
    assert [(s.filing_number, s.title) for s in profile.sources] == [
        ("20260814001234", "반기보고서 (2026.06)")
    ]
    assert profile.notes == ()
    ((query, volatility),) = search.calls
    assert volatility == "high"
    assert query.corp_code == "00126380"


async def test_no_recent_report_is_noted():
    profile = await profile_company(
        Company("00126380", 12), overview(), search_filings=Search(None), today=TODAY
    )
    assert (profile.latest_report, profile.sources, profile.notes) == (None, (), (NO_REPORT,))


@pytest.mark.parametrize(
    ("acc_mt", "month"),
    [("03", 3), ("12", 12), (" 6 ", 6), ("", 12), ("-", 12), (None, 12), ("13", 12), ("0", 12)],
)
def test_the_fiscal_year_end_month_comes_from_acc_mt_and_defaults_to_december(acc_mt, month):
    assert fiscal_year_end_month(SimpleNamespace(acc_mt=acc_mt)) == month


def test_without_an_overview_the_fiscal_year_ends_in_december():
    assert fiscal_year_end_month(None) == 12
