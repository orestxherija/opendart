"""get_financials over the MCP protocol: ratios, equity investments, and preliminary earnings."""

from __future__ import annotations

import pytest

from opendart_mcp.documents.preliminary import (
    PreliminaryChange,
    PreliminaryEarnings,
    PreliminaryPeriod,
    PreliminaryRow,
    PreliminaryValue,
)
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.preliminary import PreliminaryResult
from packages.mcp.tests.tools.financials_data import (
    T,
    by_params,
    indicator_rows,
    investment_rows,
    samsung,
)

pytestmark = pytest.mark.anyio
FAIR_DISCLOSURE = "20261008800004"


async def call(client, **arguments):
    result = await client.call_tool("get_financials", {"company": "005930", **arguments})
    return result.structured_content, result.content[0].text


def route_indicators(upstream, *years, code="11011"):
    table = {
        (str(year), code, category): upstream.rows(
            *indicator_rows(category, year=str(year), shift=index)
        )
        for index, year in enumerate(years)
        for category in ("M210000", "M220000", "M230000", "M240000")
    }
    upstream.route(
        "/fnlttSinglIndx.json", by_params(table, "bsns_year", "reprt_code", "idx_cl_code")
    )


async def test_ratios_show_key_indicators_with_clear_labels(client, upstream):
    route_indicators(upstream, 2025, 2024)
    data, text = await call(client, view="ratios", fiscal_year=2025, period="FY", years=2)
    assert [p["label"] for p in data["periods"]] == ["FY2025", "FY2024"]
    rows = data["rows"]
    assert [row["account"] for row in rows][:4] == [
        "Gross margin",
        "Net margin",
        "Return on equity",
        "Operating profit to total assets",
    ]
    assert rows[0] == {"account": "Gross margin", "kind": "percent", "values": [39.4, 40.4]}
    assert len(rows) == 12
    assert any("Showing 12 key lines of 14" in note for note in data["notes"])
    assert any("turnover ratios included" in note for note in data["notes"])
    assert "basis_used" not in data
    assert "| Gross margin | 39.4% | 40.4% |" in text
    assert "Amounts in" not in text
    assert {q["idx_cl_code"] for q in upstream.params("/fnlttSinglIndx.json")} == {
        "M210000",
        "M220000",
        "M230000",
        "M240000",
    }


async def test_detailed_ratios_include_unpublished_and_overflowing_values(client, upstream):
    route_indicators(upstream, 2025)
    data, _ = await call(
        client,
        view="ratios",
        fiscal_year=2025,
        period="FY",
        basis="consolidated",
        response_format="detailed",
    )
    rows = {row["account_id"]: row for row in data["rows"]}
    assert len(rows) == 14
    assert rows["M212400"] == {
        "account": "Return on business capital",
        "account_id": "M212400",
        "kind": "percent",
        "values": [None],
    }
    assert rows["M211100"]["values"] == [None]
    assert (
        "OpenDART does not state the basis of its indicators, so basis does not apply."
        in data["notes"]
    )


async def test_latest_ratios_cite_the_periodic_report(client, upstream):
    samsung(upstream)
    route_indicators(upstream, 2026, code="11012")
    data, _ = await call(client, view="ratios")
    assert data["periods"][0]["label"] == "H1 2026"
    assert data["source_filings"][0]["title"] == "Semi-Annual Report (2026.06)"


async def test_ratios_before_2022_are_rejected(client):
    result = await client.call_tool(
        "get_financials",
        {"company": "005930", "view": "ratios", "fiscal_year": 2021},
        raise_on_error=False,
    )
    assert result.is_error
    assert "from fiscal 2022" in result.content[0].text


async def test_ratios_without_data_explain_it(client):
    data, _ = await call(client, view="ratios", fiscal_year=2024, period="FY")
    assert data["rows"] == []
    assert "OpenDART has no financial indicators for FY2024" in data["notes"][0]


def route_investments(upstream, count=25):
    table = {("2025", "11011"): upstream.rows(*investment_rows(count))}
    upstream.route("/otrCprInvstmntSttus.json", by_params(table, "bsns_year", "reprt_code"))


async def test_equity_investments_list_the_largest_holdings_and_the_total(client, upstream):
    route_investments(upstream)
    data, text = await call(
        client, view="equity_investments", fiscal_year=2025, period="FY", years=2
    )
    assert [p["label"] for p in data["periods"]] == ["FY2025", "FY2024"]
    assert len(data["rows"]) == 21
    assert data["rows"][0] == {"account": "투자회사25", "values": [25 * T, 25 * T - 10**9]}
    assert data["rows"][-1]["account"] == "Total (all investments)"
    holding = data["investments"][0]
    assert holding == {
        "name": "투자회사25",
        "purpose": "management participation",
        "ownership_pct": 50.0,
        "shares": 1000,
        "book_value": 25 * T,
    }
    assert data["investments"][1]["purpose"] == "simple investment"
    notes = " ".join(data["notes"])
    assert "Showing the 20 largest of 25 holdings" in notes
    assert "years does not apply" in notes
    assert "| Investee | Purpose | Stake | Shares | Book value |" in text
    assert "Total book value: 325,000,000.0 (opening 324,975,000.0)." in text


async def test_detailed_equity_investments_show_every_holding_and_field(client, upstream):
    route_investments(upstream)
    data, text = await call(
        client,
        view="equity_investments",
        fiscal_year=2025,
        period="FY",
        response_format="detailed",
        unit="krw",
    )
    assert len(data["investments"]) == 25
    assert data["investments"][0]["investee_total_assets"] == 75 * T
    assert data["investments"][0]["first_acquired"] == "1995-06-29"
    assert "Investee assets" in text
    assert "| 투자회사25 | management participation | 50.0% | 1,000 | 25,000,000,000,000 |" in text


async def test_equity_investments_filter_by_name(client, upstream):
    route_investments(upstream, count=3)
    data, _ = await call(
        client, view="equity_investments", fiscal_year=2025, period="FY", accounts=["회사02"]
    )
    assert [row["account"] for row in data["rows"]] == ["투자회사02"]
    assert [item["name"] for item in data["investments"]] == ["투자회사02"]


async def test_equity_investments_without_a_table(client):
    data, _ = await call(client, view="equity_investments", fiscal_year=2025, period="FY")
    assert data["rows"] == []
    assert "equity investment table" in data["notes"][0]


def value(trillions):
    return PreliminaryValue(
        krw=None if trillions is None else int(trillions * T), raw=str(trillions)
    )


def change(percent):
    return PreliminaryChange(percent=percent, raw=str(percent))


def row(metric, label, current, prior, year_ago, ytd, prior_ytd):
    return PreliminaryRow(
        metric=metric,
        label_ko=label,
        current_quarter=value(current),
        prior_quarter=value(prior),
        year_ago_quarter=value(year_ago),
        quarter_on_quarter=change(1.0),
        year_on_year=change(2.0),
        year_to_date=value(ytd),
        prior_year_to_date=value(prior_ytd),
        year_to_date_change=change(3.0),
    )


def earnings(*, periods=True):
    spans = [
        ("current_quarter", "2026-07-01", "2026-09-30"),
        ("prior_quarter", "2026-04-01", "2026-06-30"),
        ("year_ago_quarter", "2025-07-01", "2025-09-30"),
    ]
    return PreliminaryEarnings(
        filing_number=FAIR_DISCLOSURE,
        company_name="삼성전자",
        basis="consolidated",
        unit_label="KRW 100 million",
        unit_multiplier=10**8,
        periods=[
            PreliminaryPeriod(key=key, label_ko="x", start=start, end=end)
            for key, start, end in spans
        ]
        if periods
        else [],
        rows=[
            row("revenue", "매출액", 86, 74, 80, 240, 230),
            row("operating_profit", "영업이익", 10, 5, 8, 25, 20),
            row("net_profit", "당기순이익", 8, None, 6, None, None),
        ],
        is_amendment=True,
        notes=["Parsed from the fair disclosure."],
    )


def found(**kwargs):
    return PreliminaryResult(
        earnings=earnings(**kwargs),
        source=SourceFiling.of(FAIR_DISCLOSURE, "Preliminary results"),
        notes=["A newer disclosure could not be read."],
    )


async def test_preliminary_earnings_become_quarter_columns(client, monkeypatch):
    async def latest(state, company, *, progress):
        assert company.corp_code == "00126380"
        return found()

    monkeypatch.setattr("opendart_mcp.services.financials.latest_preliminary", latest)
    data, text = await call(client, view="preliminary", period="FY")
    assert [(p["label"], p["period"], p["end_date"]) for p in data["periods"]] == [
        ("Q3 2026", "Q3", "2026-09-30"),
        ("Q2 2026", "H1", "2026-06-30"),
        ("Q3 2025", "Q3", "2025-09-30"),
    ]
    revenue = data["rows"][0]
    assert revenue == {
        "account": "Revenue",
        "values": [86 * T, 74 * T, 80 * T],
        "cumulative": [240 * T, None, 230 * T],
    }
    assert "cumulative" not in data["rows"][2]
    assert data["derived"] == {
        "revenue_growth": 7.5,
        "operating_income_growth": 25.0,
        "net_income_growth": 33.33,
        "operating_margin": 11.63,
        "net_margin": 9.3,
        "revenue_qoq_growth": 16.22,
        "operating_income_qoq_growth": 100.0,
    }
    assert data["basis_used"] == "consolidated"
    assert data["source_filings"][0]["filing_number"] == FAIR_DISCLOSURE
    notes = " ".join(data["notes"])
    for expected in (
        "unaudited",
        "corrects an earlier one",
        "KRW 100 million",
        "newer disclosure",
        "do not apply",
    ):
        assert expected in notes
    assert "| Account | Q3 2026 | 9M 2026 | Q2 2026 | Q3 2025 | 9M 2025 |" in text


async def test_preliminary_without_stated_periods_returns_a_note(client, monkeypatch):
    async def latest(state, company, *, progress):
        return found(periods=False)

    monkeypatch.setattr("opendart_mcp.services.financials.latest_preliminary", latest)
    data, _ = await call(client, view="preliminary")
    assert data["rows"] == []
    assert "does not state its periods" in " ".join(data["notes"])


async def test_no_preliminary_disclosure_is_a_note(client, monkeypatch):
    async def latest(state, company, *, progress):
        return None

    monkeypatch.setattr("opendart_mcp.services.financials.latest_preliminary", latest)
    data, text = await call(client, view="preliminary")
    assert data["rows"] == []
    assert "No preliminary earnings disclosure was found" in data["notes"][0]
    assert "Preliminary earnings" in text


async def test_preliminary_view_searches_recent_fair_disclosures(client, upstream):
    samsung(upstream)
    data, _ = await call(client, view="preliminary")
    assert data["rows"] == []
    assert "No preliminary earnings disclosure was found" in data["notes"][0]
    assert upstream.count("/list.json") >= 1
