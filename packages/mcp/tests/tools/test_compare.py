"""compare_companies over the MCP protocol."""

from __future__ import annotations

import anyio
import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from opendart_mcp.server import create_server
from packages.mcp.tests.tools.financials_data import (
    ANNUAL,
    HYNIX,
    KAKAO,
    SAMSUNG,
    T,
    by_params,
    half_summary_rows,
    indicator_rows,
    summary_rows,
)

pytestmark = pytest.mark.anyio
CATEGORIES = ("M210000", "M220000", "M230000", "M240000")


async def call(client, companies, **arguments):
    result = await client.call_tool("compare_companies", {"companies": companies, **arguments})
    return result.structured_content, result.content[0].text


def profiles(upstream, months=None):
    def route(request):
        code = request.url.params["corp_code"]
        return upstream.ok(
            corp_cls="Y" if code != KAKAO else "K", acc_mt=(months or {}).get(code, "12")
        )

    upstream.route("/company.json", route)


def route_accounts(upstream, table):
    rows = {key: upstream.rows(*value) for key, value in table.items()}
    upstream.route("/fnlttMultiAcnt.json", by_params(rows, "bsns_year", "reprt_code"))


def route_indicators(upstream, year="2025", corps=(SAMSUNG, HYNIX)):
    table = {
        (year, "11011", c): upstream.rows(*indicator_rows(c, year=year, corps=corps))
        for c in CATEGORIES
    }
    upstream.route(
        "/fnlttCmpnyIndx.json", by_params(table, "bsns_year", "reprt_code", "idx_cl_code")
    )


def two_companies(year="2025"):
    return summary_rows(year=year) + summary_rows(corp=HYNIX, year=year, scale=2)


async def test_compare_is_listed_with_its_schema(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    tool = tools["compare_companies"]
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations.read_only_hint is True
    assert tool.input_schema["required"] == ["companies"]
    assert tool.input_schema["properties"]["companies"]["maxItems"] == 20
    assert tool.input_schema["properties"]["period"]["default"] == "FY"
    assert tool.input_schema["properties"]["basis"]["default"] == "consolidated"
    assert {"columns", "rows", "missing", "fiscal_year", "period", "basis"} <= set(
        tool.output_schema["properties"]
    )


async def test_key_accounts_for_two_companies_in_one_call(client, upstream):
    profiles(upstream)
    route_accounts(upstream, {("2025", "11011"): two_companies()})
    data, text = await call(client, ["005930", "000660"])
    assert (data["fiscal_year"], data["period"], data["basis"], data["company_count"]) == (
        2025,
        "FY",
        "consolidated",
        2,
    )
    assert [c["key"] for c in data["columns"]] == [
        "revenue",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "revenue_growth",
        "operating_margin",
        "net_margin",
        "debt_to_equity",
    ]
    assert data["columns"][0] == {"key": "revenue", "label": "Revenue", "unit": "krw"}
    assert data["columns"][7] == {
        "key": "operating_margin",
        "label": "Operating margin (derived)",
        "unit": "pct",
    }
    samsung, hynix = data["rows"]
    assert samsung["company"] == {
        "name": "SAMSUNG ELECTRONICS CO,.LTD",
        "corp_code": SAMSUNG,
        "stock_code": "005930",
        "market": "KOSPI",
    }
    assert samsung["values"] == [
        330 * T,
        44 * T,
        45 * T,
        570 * T,
        125 * T,
        445 * T,
        10.0,
        13.33,
        13.64,
        28.09,
    ]
    assert hynix["values"][:2] == [660 * T, 88 * T]
    assert data["missing"] == []
    assert data["source_filings"] == [
        {
            "filing_number": ANNUAL,
            "filed": "2026-03-10",
            "dart_url": data["source_filings"][0]["dart_url"],
        }
    ]
    assert any("revenue_growth = change versus FY2024" in note for note in data["notes"])
    assert "| Company | Revenue | Operating profit |" in text
    assert "| SAMSUNG ELECTRONICS CO,.LTD (005930) | 330,000,000.0 | 44,000,000.0 |" in text
    assert "Peer comparison: FY2025, consolidated basis, 2 companies" in text
    assert upstream.count("/fnlttMultiAcnt.json") == 1
    assert upstream.params("/fnlttMultiAcnt.json")[0]["corp_code"] == "00126380,00164779"


async def test_unresolvable_inputs_are_listed_as_missing(client, upstream):
    profiles(upstream)
    route_accounts(upstream, {("2025", "11011"): two_companies()})
    data, text = await call(client, ["005930", "Samsung", "zzzz nothing", "20260310002820"])
    assert data["company_count"] == 1
    reasons = {item["company"]: item["reason"] for item in data["missing"]}
    assert "Ambiguous company" in reasons["Samsung"]
    assert "find_company" in reasons["zzzz nothing"]
    assert "filing number" in reasons["20260310002820"]
    assert "Not included: Samsung:" in text


async def test_a_missing_basis_is_reported_unless_auto(client, upstream):
    profiles(upstream)
    route_accounts(
        upstream, {("2025", "11011"): summary_rows() + summary_rows(corp=KAKAO, scopes=("OFS",))}
    )
    data, _ = await call(client, ["005930", "035720"])
    assert [row["company"]["corp_code"] for row in data["rows"]] == [SAMSUNG]
    assert data["missing"] == [
        {
            "company": "Kakao Corp.",
            "reason": 'No consolidated statements for FY2025; pass basis="auto".',
        }
    ]
    data, _ = await call(client, ["005930", "035720"], basis="auto")
    assert [row["basis_used"] for row in data["rows"]] == ["consolidated", "separate"]
    assert "Separate statements used for: Kakao Corp.." in data["notes"]


async def test_ratios_use_published_indicators(client, upstream):
    profiles(upstream)
    route_indicators(upstream)
    data, text = await call(client, ["005930", "000660"], metrics="ratios")
    assert [c["key"] for c in data["columns"]] == [
        "gross_margin",
        "net_margin",
        "roe",
        "operating_roa",
        "debt_to_equity",
        "current_ratio",
        "revenue_growth",
        "operating_income_growth",
        "net_income_growth",
        "asset_turnover",
    ]
    assert all(c["unit"] == "pct" for c in data["columns"])
    assert [row["values"][0] for row in data["rows"]] == [39.4, 40.4]
    assert any("turnover ratios included" in note for note in data["notes"])
    assert "| SAMSUNG ELECTRONICS CO,.LTD (005930) | 39.4% |" in text
    assert "Amounts in" not in text
    assert upstream.count("/fnlttCmpnyIndx.json") == 4
    assert upstream.count("/fnlttMultiAcnt.json") == 0


async def test_both_drops_derived_columns_that_indicators_cover(client, upstream):
    profiles(upstream)
    route_accounts(upstream, {("2025", "11011"): two_companies()})
    route_indicators(upstream)
    data, _ = await call(client, ["005930", "000660"], metrics="both", response_format="detailed")
    labels = {c["key"]: c["label"] for c in data["columns"]}
    keys = [c["key"] for c in data["columns"]]
    assert labels["operating_margin"] == "Operating margin (derived)"
    assert labels["current_ratio"] == "Current ratio"
    assert all(keys.count(key) == 1 for key in ("current_ratio", "net_margin", "debt_to_equity"))
    assert "m212400" in keys
    assert data["rows"][0]["company"]["korean_name"] == "삼성전자"


async def test_the_period_with_data_for_the_most_companies_wins(client, upstream):
    profiles(upstream)
    route_accounts(
        upstream, {("2025", "11011"): summary_rows(), ("2024", "11011"): two_companies(year="2024")}
    )
    data, _ = await call(client, ["005930", "000660"])
    assert data["fiscal_year"] == 2024
    assert data["company_count"] == 2
    assert "FY2024 is the newest period with data for the most companies (2 of 2)." in data["notes"]


async def test_quarterly_comparisons_use_year_to_date_amounts(client, upstream):
    profiles(upstream, months={HYNIX: "3"})
    rows = half_summary_rows() + half_summary_rows(corp=HYNIX)
    upstream.route(
        "/fnlttMultiAcnt.json",
        by_params({("2026", "11012"): upstream.rows(*rows)}, "bsns_year", "reprt_code"),
    )
    data, _ = await call(client, ["005930", "000660"], period="H1", fiscal_year=2026)
    assert data["period"] == "H1"
    assert data["rows"][0]["values"][0] == 300 * T
    assert data["rows"][0]["values"][6] == 100.0
    assert "Quarterly income amounts are year to date." in data["notes"]
    assert any(
        "Fiscal years not ending in December: SK hynix Inc." in note for note in data["notes"]
    )


async def test_without_data_every_company_is_missing(client, upstream):
    profiles(upstream)
    data, text = await call(client, ["005930"])
    assert data["rows"] == []
    assert data["columns"] == []
    assert "fiscal_year" not in data
    assert data["missing"][0]["company"] == "SAMSUNG ELECTRONICS CO,.LTD"
    assert "No company has data for the requested period; see missing." in data["notes"]
    assert "**Peer comparison (consolidated basis)**" in text


async def test_nothing_resolvable_is_explained(client):
    data, _ = await call(client, ["zzzz nothing"])
    assert data["company_count"] == 0
    assert "No company could be resolved; see missing." in data["notes"]


async def test_duplicates_are_merged_and_companies_without_indicators_are_missing(client, upstream):
    profiles(upstream)
    route_indicators(upstream, corps=(SAMSUNG,))
    data, _ = await call(client, ["005930", "00126380", "000660"], metrics="ratios")
    assert data["company_count"] == 1
    assert "1 duplicate input(s) resolved to the same company and were merged." in data["notes"]
    assert data["missing"] == [
        {"company": "SK hynix Inc.", "reason": "No FY2025 indicators in OpenDART."}
    ]


async def test_both_before_2022_shows_accounts_only(client, upstream):
    profiles(upstream)
    route_accounts(upstream, {("2021", "11011"): two_companies(year="2021")})
    data, _ = await call(client, ["005930", "000660"], metrics="both", fiscal_year=2021)
    assert [c["key"] for c in data["columns"]][-1] == "debt_to_equity"
    assert (
        "OpenDART publishes indicators from fiscal 2022; only accounts are shown." in data["notes"]
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"metrics": "ratios", "fiscal_year": 2021}, "from fiscal 2022"),
        ({"fiscal_year": 2030}, "has not ended yet"),
    ],
)
async def test_unusable_periods_are_rejected(client, upstream, arguments, message):
    profiles(upstream)
    result = await client.call_tool(
        "compare_companies", {"companies": ["005930"], **arguments}, raise_on_error=False
    )
    assert result.is_error
    assert message in result.content[0].text


async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    server = create_server(mcp_settings, transport=upstream.transport)
    async with Client(server) as client:
        result = await client.call_tool(
            "compare_companies", {"companies": ["005930"]}, raise_on_error=False
        )
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text
    assert upstream.count() == 0


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_ambiguous_inputs_are_asked_about_one_at_a_time(server, upstream, mode):
    profiles(upstream)
    route_accounts(upstream, {("2025", "11011"): two_companies()})
    asked: list[str] = []
    open_dialogs = [0, 0]  # now, most at once

    async def handler(message, response_type, params, context):
        asked.append(message)
        open_dialogs[0] += 1
        open_dialogs[1] = max(open_dialogs)
        await anyio.sleep(0.02)  # the user takes a moment to answer
        open_dialogs[0] -= 1
        if "'Samsung'" not in message:
            return ElicitResult(action="decline")
        try:  # 2026-07-28 guard requests carry an object schema; 2025-11-25 a list of choices
            content = response_type(corp_code=SAMSUNG)
        except TypeError:
            content = response_type(value=SAMSUNG)
        return ElicitResult(action="accept", content=content)

    async with Client(server, mode=mode, elicitation_handler=handler) as client:
        data, _ = await call(client, ["Samsung", "000660", "삼성", "SAMSUNG E"])
    assert open_dialogs[1] == 1
    assert asked == [
        f"'{query}' matches several companies. Which one do you mean?"
        for query in ("Samsung", "삼성", "SAMSUNG E")
    ]
    assert [row["company"]["corp_code"] for row in data["rows"]] == [SAMSUNG, HYNIX]
    assert [item["company"] for item in data["missing"]] == ["삼성", "SAMSUNG E"]
