"""get_dividends over the MCP protocol."""

from __future__ import annotations

import pytest

PROFILE = {
    "corp_name": "삼성전자",
    "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
    "stock_code": "005930",
    "corp_cls": "Y",
    "acc_mt": "12",
}
ANNUAL = "20260310002820"


def report(number, title):
    return {
        "corp_cls": "Y",
        "corp_name": "SAMSUNG ELECTRONICS CO,.LTD",
        "corp_code": "00126380",
        "stock_code": "005930",
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": "삼성전자",
        "rcept_dt": number[:8],
        "rm": "",
    }


def samsung(upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    upstream.records(
        "/list.json",
        report("20260814001234", "Semi-Annual Report (2026.06)"),
        report(ANNUAL, "Annual Report (2025.12)"),
    )


def line(label, stock, values, number=ANNUAL):
    current, prior, older = values
    return {
        "rcept_no": number,
        "se": label,
        "stock_knd": stock,
        "thstrm": current,
        "frmtrm": prior,
        "lwfr": older,
        "stlm_dt": "2025-12-31",
    }


def dividend_table(number=ANNUAL, scale=1):
    def amount(value):
        return f"{value * scale:,}"

    return (
        line("Par value per share (KRW)", "-", ("100", "100", "100"), number),
        line(
            "(Consolidated) profit (KRW million)",
            "-",
            (amount(44_000), amount(33_000), amount(14_000)),
            number,
        ),
        line(
            "(Non-consolidated) net profit during the term (KRW million)",
            "-",
            (amount(33_000), amount(23_000), amount(25_000)),
            number,
        ),
        line("(Consolidated) Net profit per share (KRW)", "-", ("6,605", "4,950", "2,131"), number),
        line(
            "Total cash dividends (KRW million)",
            "-",
            (amount(11_000), amount(9_800), amount(9_800)),
            number,
        ),
        line("Total share dividends (KRW million)", "-", ("-", "-", "-"), number),
        line(
            "(Consolidated) cash dividend payout ratio (%)",
            "-",
            ("25.10", "29.20", "67.80"),
            number,
        ),
        line("Cash dividend rate of return (%)", "보통주", ("1.50", "2.70", "1.90"), number),
        line("Cash dividend rate of return (%)", "우선주", ("1.90", "3.30", "2.40"), number),
        line("Cash dividend per share (KRW)", "보통주", ("1,668", "1,446", "1,444"), number),
        line("Cash dividend per share (KRW)", "우선주", ("1,669", "1,447", "1,445"), number),
        line("Stock dividend per share (share)", "보통주", ("-", "-", "-"), number),
    )


@pytest.mark.anyio
async def test_dividends_are_listed_with_schema_version_and_annotations(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    tool = tools["get_dividends"]
    assert tool.meta is not None
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    years = tool.input_schema["properties"]["years"]
    assert (years["default"], years["minimum"], years["maximum"]) == (3, 1, 10)
    assert set(tool.input_schema["properties"]) == {"company", "years", "response_format"}
    assert tool.output_schema is not None
    assert {"rows", "fiscal_years"} <= set(tool.output_schema["properties"])
    assert 60 <= len((tool.description or "").split()) <= 120


@pytest.mark.anyio
async def test_dividends_by_share_class_and_year(client, upstream):
    samsung(upstream)
    upstream.records("/alotMatter.json", *dividend_table())
    result = await client.call_tool("get_dividends", {"company": "005930"})
    data = result.structured_content
    assert data["fiscal_years"] == [2025, 2024, 2023]
    rows = {(r["measure"], r.get("share_class"), r.get("basis")): r for r in data["rows"]}
    assert rows[("cash_dps", "common", None)] == {
        "measure": "cash_dps",
        "share_class": "common",
        "unit": "KRW/share",
        "values_by_year": {"2025": 1668, "2024": 1446, "2023": 1444},
    }
    assert rows[("cash_dividends", None, None)]["values_by_year"]["2025"] == 11_000_000_000
    assert rows[("cash_dividends", None, None)]["unit"] == "KRW"
    assert rows[("payout_ratio", None, "consolidated")]["values_by_year"]["2023"] == 67.8
    assert rows[("cash_yield", "preferred", None)]["values_by_year"]["2025"] == 1.9
    assert rows[("net_income", None, "separate")]["values_by_year"]["2024"] == 23_000_000_000
    assert ("par_value", None, None) not in rows
    assert ("stock_dividends", None, None) not in rows
    assert any("Yields are as filed" in note for note in data["notes"])
    assert data["source_filings"][0]["title"] == "Annual Report (2025.12)"
    text = result.content[0].text
    assert "| Measure | Share class | FY2025 | FY2024 | FY2023 |" in text
    assert "| Cash dividend per share (KRW) | common | 1,668 | 1,446 | 1,444 |" in text
    assert "| Total cash dividends (KRW million) | - | 11,000.0 | 9,800.0 | 9,800.0 |" in text
    assert "| Cash payout ratio, consolidated | - | 25.10% | 29.20% | 67.80% |" in text
    params = upstream.params("/alotMatter.json")
    assert params == [{"corp_code": "00126380", "bsns_year": "2025", "reprt_code": "11011"}]


@pytest.mark.anyio
async def test_five_years_chain_an_earlier_annual_report(client, upstream):
    samsung(upstream)
    older = "20230310000999"

    def by_year(request):
        if request.url.params["bsns_year"] == "2022":
            return upstream.rows(*dividend_table(older))
        return upstream.rows(*dividend_table())

    upstream.route("/alotMatter.json", by_year)
    result = await client.call_tool("get_dividends", {"company": "005930", "years": 5})
    data = result.structured_content
    assert data["fiscal_years"] == [2025, 2024, 2023, 2022, 2021]
    dps = next(r for r in data["rows"] if r["measure"] == "cash_dps")
    assert list(dps["values_by_year"]) == ["2025", "2024", "2023", "2022", "2021"]
    assert sorted(p["bsns_year"] for p in upstream.params("/alotMatter.json")) == ["2022", "2025"]
    assert [s["filing_number"] for s in data["source_filings"]] == [ANNUAL, older]


@pytest.mark.anyio
async def test_one_year_and_detailed_rows(client, upstream):
    samsung(upstream)
    upstream.records("/alotMatter.json", *dividend_table())
    result = await client.call_tool(
        "get_dividends", {"company": "005930", "years": 1, "response_format": "detailed"}
    )
    data = result.structured_content
    assert data["fiscal_years"] == [2025]
    par = next(r for r in data["rows"] if r["measure"] == "par_value")
    assert par == {
        "measure": "par_value",
        "unit": "KRW/share",
        "values_by_year": {"2025": 100},
        "label": "Par value per share (KRW)",
    }
    stock = next(r for r in data["rows"] if r["measure"] == "stock_dividends")
    assert stock["values_by_year"] == {}
    assert "| Stock dividend per share (shares) | common | - |" in result.content[0].text


@pytest.mark.anyio
async def test_a_missing_earlier_report_is_noted(client, upstream):
    samsung(upstream)

    def latest_only(request):
        if request.url.params["bsns_year"] == "2025":
            return upstream.rows(*dividend_table())
        return upstream.status("013")

    upstream.route("/alotMatter.json", latest_only)
    result = await client.call_tool("get_dividends", {"company": "005930", "years": 6})
    data = result.structured_content
    assert data["fiscal_years"] == [2025, 2024, 2023]
    assert "No dividend table for FY2022; earlier years are missing." in data["notes"]


@pytest.mark.anyio
async def test_no_dividend_table_is_an_empty_result_with_a_note(client, upstream):
    samsung(upstream)
    result = await client.call_tool("get_dividends", {"company": "005930"})
    data = result.structured_content
    assert data["rows"] == []
    assert data["fiscal_years"] == []
    assert data["notes"] == ['OpenDART has no dividend table in "Annual Report (2025.12)".']
    assert upstream.count("/alotMatter.json") == 1


@pytest.mark.anyio
async def test_tables_without_yields_skip_the_yield_note(client, upstream):
    samsung(upstream)
    upstream.records(
        "/alotMatter.json", line("Cash dividend per share (KRW)", "보통주", ("500", "-", "-"))
    )
    result = await client.call_tool("get_dividends", {"company": "005930"})
    data = result.structured_content
    assert data["notes"] == []
    assert data["fiscal_years"] == [2025]


@pytest.mark.anyio
async def test_unknown_companies_are_errors(client):
    result = await client.call_tool("get_dividends", {"company": "999999"}, raise_on_error=False)
    assert result.is_error
    assert "find_company" in result.content[0].text


@pytest.mark.anyio
async def test_out_of_range_years_are_rejected(client):
    result = await client.call_tool(
        "get_dividends", {"company": "005930", "years": 11}, raise_on_error=False
    )
    assert result.is_error
