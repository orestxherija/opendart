"""get_financials over the MCP protocol: summary and full-statement views, and errors."""

from __future__ import annotations

import pytest
from fastmcp import Client

from opendart_mcp.server import create_server
from packages.mcp.tests.tools.financials_data import (
    ANNUAL,
    HALF,
    T,
    by_params,
    full_rows,
    half_full_rows,
    half_summary_rows,
    samsung,
    summary_rows,
)

pytestmark = pytest.mark.anyio


async def call(client, **arguments):
    result = await client.call_tool("get_financials", {"company": "005930", **arguments})
    return result.structured_content, result.content[0].text


def route_summary(upstream, **answers):
    table = {key: upstream.rows(*rows) for key, rows in answers.items()}
    upstream.route(
        "/fnlttSinglAcnt.json",
        by_params({tuple(k.split("_")): v for k, v in table.items()}, "bsns_year", "reprt_code"),
    )


def route_full(upstream, table):
    upstream.route("/fnlttSinglAcntAll.json", by_params(table, "bsns_year", "reprt_code", "fs_div"))


async def test_tools_are_listed_with_versions_annotations_and_schemas(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    names = list(tools)
    assert names.index("compare_companies") == names.index("get_financials") + 1
    tool = tools["get_financials"]
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False
    assert tool.input_schema["required"] == ["company"]
    assert tool.input_schema["properties"]["years"]["maximum"] == 5
    assert {"view", "basis_used", "unit", "periods", "rows", "derived"} <= set(
        tool.output_schema["properties"]
    )


async def test_latest_summary_is_the_half_year_with_quarter_and_year_to_date(client, upstream):
    samsung(upstream)
    route_summary(upstream, **{"2026_11012": half_summary_rows()})
    data, text = await call(client)
    assert data["view"] == "summary"
    assert data["basis_used"] == "consolidated"
    assert [(p["label"], p["end_date"], p["period"]) for p in data["periods"]] == [
        ("H1 2026", "2026-06-30", "H1"),
        ("FY2025", "2025-12-31", "FY"),
        ("H1 2025", "2025-06-30", "H1"),
    ]
    rows = {row["account"]: row for row in data["rows"]}
    assert list(rows)[:3] == ["Sales", "Operating income", "Profit"]
    assert rows["Sales"]["values"] == [170 * T, None, 75 * T]
    assert rows["Sales"]["cumulative"] == [300 * T, None, 150 * T]
    assert rows["Total assets"]["values"] == [760 * T, 570 * T, None]
    assert "cumulative" not in rows["Total assets"]
    assert data["derived"] == {
        "revenue_growth": 100.0,
        "operating_income_growth": 1218.18,
        "net_income_growth": 807.69,
        "operating_margin": 48.33,
        "net_margin": 39.33,
        "debt_to_equity": 31.03,
        "current_ratio": 281.48,
    }
    assert data["source_filings"][0]["title"] == "Semi-Annual Report (2026.06)"
    assert any("three-month amounts" in note for note in data["notes"])
    assert any("H1 2026 (year to date)" in note for note in data["notes"])
    assert "| Account | Q2 2026 | H1 2026 | FY2025 | Q2 2025 | H1 2025 |" in text
    assert "| Sales | 170,000,000.0 | 300,000,000.0 | - | 75,000,000.0 | 150,000,000.0 |" in text
    assert "Derived (computed, see notes): revenue growth +100.0%" in text
    assert upstream.params("/fnlttSinglAcnt.json")[0] == {
        "corp_code": "00126380",
        "bsns_year": "2026",
        "reprt_code": "11012",
    }


async def test_annual_summary_in_billions_drops_duplicate_lines(client, upstream):
    route_summary(upstream, **{"2025_11011": summary_rows()})
    data, text = await call(client, fiscal_year=2025, period="FY", unit="billion_krw")
    assert [p["label"] for p in data["periods"]] == ["FY2025", "FY2024", "FY2023"]
    accounts = [row["account"] for row in data["rows"]]
    assert accounts[:5] == [
        "Sales",
        "Operating income",
        "Profit(loss) before income tax",
        "Profit",
        "Total comprehensive income(loss)",
    ]
    assert "Profit(loss)" not in accounts
    assert data["derived"]["revenue_growth"] == 10.0
    assert data["derived"]["debt_to_equity"] == 28.09
    assert data["unit"] == "billion_krw"
    assert "| Sales | 330,000.0 | 300,000.0 | 260,000.0 |" in text
    assert "Amounts in KRW billion" in text
    assert upstream.count("/list.json") == 0
    assert data["source_filings"] == [
        {
            "filing_number": ANNUAL,
            "filed": "2026-03-10",
            "dart_url": data["source_filings"][0]["dart_url"],
        }
    ]


async def test_years_chain_earlier_reports_three_years_apart(client, upstream):
    route_summary(
        upstream, **{"2025_11011": summary_rows(), "2022_11011": summary_rows(year="2022")}
    )
    data, _ = await call(client, fiscal_year=2025, period="FY", years=3)
    assert [p["fiscal_year"] for p in data["periods"]] == [2025, 2024, 2023, 2022, 2021, 2020]
    assert {q["bsns_year"] for q in upstream.params("/fnlttSinglAcnt.json")} == {
        "2025",
        "2022",
        "2019",
    }
    assert any("No data for FY2019" in note for note in data["notes"])


async def test_auto_basis_falls_back_to_separate_statements(client, upstream):
    route_summary(upstream, **{"2025_11011": summary_rows(scopes=("OFS",))})
    data, text = await call(client, fiscal_year=2025, period="FY")
    assert data["basis_used"] == "separate"
    assert data["rows"][0]["values"][0] == 231 * T
    assert "No consolidated statements are filed for FY2025" in " ".join(data["notes"])
    assert "Financial summary (separate)" in text


async def test_consolidated_basis_without_consolidated_statements_is_empty(client, upstream):
    route_summary(upstream, **{"2025_11011": summary_rows(scopes=("OFS",))})
    data, text = await call(client, fiscal_year=2025, period="FY", basis="consolidated")
    assert data["rows"] == []
    assert data["periods"] == []
    assert 'basis="auto" falls back to separate statements' in data["notes"][0]
    assert "No rows to show." in text


async def test_income_statement_shows_key_lines_first(client, upstream):
    route_full(upstream, {("2025", "11011", "CFS"): upstream.rows(*full_rows())})
    data, text = await call(client, view="income", fiscal_year=2025, period="FY")
    accounts = [row["account"] for row in data["rows"]]
    assert accounts == [
        "Revenue",
        "Cost of sales",
        "Gross profit",
        "Selling and administrative expenses",
        "Operating profit",
        "Profit for the year",
        "Basic earnings per share",
    ]
    eps = data["rows"][-1]
    assert eps["kind"] == "per_share"
    assert eps["values"] == [6600, 4950, 2130]
    assert "account_id" not in eps
    assert any("Showing 7 key lines of 10" in note for note in data["notes"])
    assert data["derived"] == {
        "revenue_growth": 10.0,
        "operating_income_growth": 33.33,
        "net_income_growth": 32.35,
        "operating_margin": 13.33,
        "net_margin": 13.64,
    }
    assert "| Basic earnings per share (KRW) | 6,600 | 4,950 | 2,130 |" in text


async def test_detailed_income_statement_lists_every_line_with_ids(client, upstream):
    route_full(upstream, {("2025", "11011", "CFS"): upstream.rows(*full_rows())})
    data, _ = await call(
        client, view="income", fiscal_year=2025, period="FY", response_format="detailed"
    )
    rows = data["rows"]
    assert len(rows) == 10
    assert rows[0]["account_id"] == "ifrs-full_Revenue"
    others = [row for row in rows if row["account"] == "Other"]
    assert [row["values"][0] for row in others] == [1 * T, 3 * T]
    assert all("account_id" not in row for row in others)


async def test_accounts_filter_matches_names_and_reports_misses(client, upstream):
    route_full(upstream, {("2025", "11011", "CFS"): upstream.rows(*full_rows())})
    data, _ = await call(
        client, view="income", fiscal_year=2025, period="FY", accounts=["revenue", "OPERATING"]
    )
    assert [row["account"] for row in data["rows"]] == [
        "Revenue",
        "Operating profit",
        "Other non-operating income",
    ]
    data, _ = await call(client, view="income", fiscal_year=2025, period="FY", accounts=["EBITDA"])
    assert data["rows"] == []
    assert any(
        "No line matches accounts=['EBITDA']; lines include Revenue" in note
        for note in data["notes"]
    )


async def test_quarterly_income_statement_has_three_month_and_year_to_date_columns(
    client, upstream
):
    route_full(upstream, {("2026", "11012", "CFS"): upstream.rows(*half_full_rows())})
    data, text = await call(client, view="income", fiscal_year=2026, period="H1")
    assert [p["label"] for p in data["periods"]] == ["H1 2026", "H1 2025"]
    revenue = data["rows"][0]
    assert revenue["values"] == [170 * T, 75 * T]
    assert revenue["cumulative"] == [300 * T, 150 * T]
    assert data["derived"]["operating_margin"] == 48.33
    assert "| Account | Q2 2026 | H1 2026 | Q2 2025 | H1 2025 |" in text


async def test_quarterly_balance_sheet_compares_with_the_prior_year_end(client, upstream):
    route_full(upstream, {("2026", "11012", "CFS"): upstream.rows(*half_full_rows())})
    data, _ = await call(client, view="balance", fiscal_year=2026, period="H1")
    assert [p["label"] for p in data["periods"]] == ["H1 2026", "FY2025"]
    assert [row["account"] for row in data["rows"]] == [
        "Total assets",
        "Current assets",
        "Total liabilities",
        "Current liabilities",
        "Total equity",
    ]
    assert data["derived"] == {"debt_to_equity": 31.03, "current_ratio": 281.48}
    assert any("computed in code for H1 2026 from" in note for note in data["notes"])


async def test_quarterly_cash_flows_are_year_to_date(client, upstream):
    route_full(upstream, {("2026", "11012", "CFS"): upstream.rows(*half_full_rows())})
    data, _ = await call(client, view="cash_flow", fiscal_year=2026, period="H1")
    assert data["rows"][0]["values"] == [60 * T, 30 * T]
    assert "Quarterly cash flows and equity changes are year-to-date amounts." in data["notes"]
    assert data["derived"] == {}


async def test_annual_cash_flow_and_comprehensive_income(client, upstream):
    route_full(upstream, {("2025", "11011", "CFS"): upstream.rows(*full_rows())})
    data, text = await call(client, view="cash_flow", fiscal_year=2025, period="FY")
    assert data["rows"][0]["account"] == "Cash flows from (used in) operating activities"
    assert "-13,000,000.0" in text
    data, _ = await call(client, view="comprehensive_income", fiscal_year=2025, period="FY")
    assert [row["account"] for row in data["rows"]] == [
        "Profit for the year",
        "Total comprehensive income for the year",
    ]


async def test_equity_changes_show_whole_equity_lines_unless_detailed(client, upstream):
    route_full(upstream, {("2025", "11011", "CFS"): upstream.rows(*full_rows())})
    data, _ = await call(client, view="equity_changes", fiscal_year=2025, period="FY")
    assert [row["account"] for row in data["rows"]] == [
        "Equity at beginning of period",
        "Dividends declared",
        "Total equity",
    ]
    data, _ = await call(
        client, view="equity_changes", fiscal_year=2025, period="FY", response_format="detailed"
    )
    accounts = [row["account"] for row in data["rows"]]
    assert accounts[3:] == [
        "Equity at beginning of period (Retained earnings)",
        "Dividends declared (Retained earnings)",
        "Total equity (Retained earnings)",
        "Profit for the year (Non-controlling interests)",
    ]


async def test_full_statements_fall_back_to_separate_and_report_the_currency(client, upstream):
    route_full(upstream, {("2025", "11011", "OFS"): upstream.rows(*full_rows(currency="USD"))})
    data, text = await call(client, view="balance", fiscal_year=2025, period="FY")
    assert data["basis_used"] == "separate"
    accounts = [row["account"] for row in data["rows"]]
    assert accounts[accounts.index("Current liabilities") + 1] == "Short-term borrowings"
    assert data["currency"] == "USD"
    assert any("Amounts are in USD, not won" in note for note in data["notes"])
    assert "Amounts in USD million" in text
    assert [q["fs_div"] for q in upstream.params("/fnlttSinglAcntAll.json")] == ["CFS", "OFS"]


async def test_single_statement_of_comprehensive_income_serves_the_income_view(client, upstream):
    rows = [row | {"sj_div": "CIS"} for row in full_rows() if row["sj_div"] == "IS"]
    route_full(upstream, {("2025", "11011", "CFS"): upstream.rows(*rows)})
    data, _ = await call(client, view="income", fiscal_year=2025, period="FY")
    assert data["rows"][0]["account"] == "Revenue"
    assert "single statement of comprehensive income" in " ".join(data["notes"])


async def test_no_data_is_an_empty_result_with_a_note(client, upstream):
    samsung(upstream)
    data, text = await call(client)
    assert data["rows"] == []
    assert "OpenDART has no major accounts for H1 2026" in data["notes"][0]
    assert "As of 2026-10-22 (KST)." in text


async def test_latest_falls_back_to_an_older_period_with_data(client, upstream):
    samsung(upstream)
    route_summary(upstream, **{"2026_11013": summary_rows(year="2026")})
    data, _ = await call(client)
    assert data["periods"][0]["label"] == "Q1 2026"
    assert "OpenDART has no data for H1 2026 yet; showing Q1 2026." in data["notes"]


async def test_periods_that_have_not_ended_are_rejected(client):
    result = await client.call_tool(
        "get_financials",
        {"company": "005930", "fiscal_year": 2030, "period": "FY"},
        raise_on_error=False,
    )
    assert result.is_error
    assert "has not ended yet" in result.content[0].text


async def test_ambiguous_names_return_candidates(client):
    result = await client.call_tool("get_financials", {"company": "Samsung"}, raise_on_error=False)
    assert result.is_error
    assert "Ambiguous company" in result.content[0].text


async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    server = create_server(mcp_settings, transport=upstream.transport)
    async with Client(server) as client:
        result = await client.call_tool(
            "get_financials", {"company": "00126380"}, raise_on_error=False
        )
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text


async def test_half_year_filing_is_cited(client, upstream):
    samsung(upstream)
    route_summary(upstream, **{"2026_11012": half_summary_rows()})
    data, text = await call(client, accounts=["sales"])
    assert [row["account"] for row in data["rows"]] == ["Sales"]
    assert data["source_filings"][0]["filing_number"] == HALF
    assert f"Sources: {HALF} (Semi-Annual Report (2026.06), 2026-08-14)." in text


async def test_full_statements_without_data_explain_it(client, upstream):
    data, _ = await call(client, view="income", fiscal_year=2025, period="FY")
    assert data["rows"] == []
    assert data["notes"][0].startswith("OpenDART has no income statement for FY2025")
    assert [q["fs_div"] for q in upstream.params("/fnlttSinglAcntAll.json")] == ["CFS", "OFS"]


@pytest.mark.parametrize(
    ("company", "message"),
    [("999999", "find_company"), ("20260310002820", "is a filing number")],
)
async def test_unusable_company_arguments_are_explained(client, company, message):
    result = await client.call_tool("get_financials", {"company": company}, raise_on_error=False)
    assert result.is_error
    assert message in result.content[0].text


async def test_quota_errors_surface_from_concurrent_calls(client, upstream):
    upstream.route("/fnlttSinglIndx.json", upstream.status("020"))
    arguments = {"company": "005930", "view": "ratios", "fiscal_year": 2025, "period": "FY"}
    result = await client.call_tool("get_financials", arguments, raise_on_error=False)
    assert result.is_error
    assert "quota" in result.content[0].text
