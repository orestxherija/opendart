"""get_debt_profile over the MCP protocol."""

from __future__ import annotations

import datetime as dt

import pytest
from fastmcp import Client

from opendart_mcp.server import create_server

PROFILE = {
    "corp_name": "삼성전자",
    "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
    "stock_code": "005930",
    "corp_cls": "Y",
    "acc_mt": "12",
}
LATEST = "20260814001234"
DEBT_PATHS = (
    "/cprndNrdmpBlce.json",
    "/srtpdPsndbtNrdmpBlce.json",
    "/entrprsBilScritsNrdmpBlce.json",
    "/newCaplScritsNrdmpBlce.json",
    "/cndlCaplScritsNrdmpBlce.json",
    "/detScritsIsuAcmslt.json",
)


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


def samsung(upstream, *reports):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    upstream.records(
        "/list.json",
        *(
            reports
            or (
                report(LATEST, "Semi-Annual Report (2026.06)"),
                report("20260310002820", "Annual Report (2025.12)"),
            )
        ),
    )


def balance(kind, **columns):
    return {
        "rcept_no": LATEST,
        "remndr_exprtn1": "Unredeemed balance",
        "remndr_exprtn2": kind,
        **columns,
    }


def issue(**fields):
    record = {
        "rcept_no": LATEST,
        "isu_cmpny": "삼성전자㈜",
        "scrits_knd_nm": "Corporate Bonds",
        "isu_mth_nm": "Public offering",
        "isu_de": "2026.02.21",
        "facvalu_totamt": "150,000,000,000",
        "intrt": "3.36 ",
        "evl_grad_instt": "AA-(한국기업평가/NICE신용평가)",
        "mtd": "2029.02.21",
        "repy_at": "미상환",
        "mngt_cmpny": "가나증권",
        "stlm_dt": "2026-06-30",
    }
    return record | fields


def debt_tables(upstream):
    upstream.records(
        "/cprndNrdmpBlce.json",
        balance(
            "Public offering",
            yy1_below="100,000,000,000",
            yy2_excess_yy3_below="150,000,000,000",
            sm="250,000,000,000",
        ),
        balance("Private placement", sm="-"),
        balance(
            "Total",
            yy1_below="100,000,000,000",
            yy2_excess_yy3_below="150,000,000,000",
            sm="250,000,000,000",
        ),
    )
    upstream.records(
        "/entrprsBilScritsNrdmpBlce.json",
        balance(
            "Total",
            de10_below="20,000,000,000",
            de30_excess_de90_below="30,000,000,000",
            sm="50,000,000,000",
        ),
    )
    upstream.records(
        "/detScritsIsuAcmslt.json",
        issue(),
        issue(
            scrits_knd_nm="Commercial Paper",
            isu_mth_nm="-",
            isu_de="2026.01.03",
            mtd="2026.04.04",
            repy_at="상환",
            evl_grad_instt="A1(한국기업평가)",
            facvalu_totamt="20,000,000,000",
        ),
        issue(
            isu_cmpny="Samsung Display Holdings",
            scrits_knd_nm="Hybrid Securities",
            isu_mth_nm="Private placement",
            mtd="2056.04.01",
            evl_grad_instt="-",
        ),
        issue(
            isu_cmpny="Total",
            scrits_knd_nm="-",
            isu_mth_nm="-",
            isu_de="-",
            facvalu_totamt="320,000,000,000",
            intrt="-",
            evl_grad_instt="-",
            mtd="-",
            repy_at="-",
            mngt_cmpny="-",
        ),
    )


@pytest.mark.anyio
async def test_debt_profile_is_listed_with_schema_version_and_annotations(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    tool = tools["get_debt_profile"]
    assert tool.meta is not None
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False
    assert tool.input_schema["required"] == ["company"]
    assert set(tool.input_schema["properties"]) == {
        "company",
        "period",
        "fiscal_year",
        "response_format",
    }
    assert tool.output_schema is not None
    assert {"ladder", "issuance", "derived", "company", "as_of"} <= set(
        tool.output_schema["properties"]
    )
    assert 60 <= len((tool.description or "").split()) <= 120


@pytest.mark.anyio
async def test_debt_profile_builds_the_ladder_and_open_issues(client, upstream):
    samsung(upstream)
    debt_tables(upstream)
    result = await client.call_tool("get_debt_profile", {"company": "005930"})
    data = result.structured_content
    assert (data["fiscal_year"], data["period"], data["period_end"]) == (2026, "H1", "2026-06-30")
    bonds, paper = data["ladder"]
    assert bonds == {
        "instrument": "corporate_bonds",
        "buckets": [
            {"maturity_bucket": "<=1y", "amount": 100_000_000_000},
            {"maturity_bucket": "2-3y", "amount": 150_000_000_000},
        ],
        "total": 250_000_000_000,
        "public": 250_000_000_000,
    }
    assert paper["buckets"] == [{"maturity_bucket": "<=1y", "amount": 50_000_000_000}]
    assert data["derived"] == {
        "total_debt_securities": 300_000_000_000,
        "due_within_1y": 150_000_000_000,
        "due_within_1y_pct": 50.0,
    }
    first, hybrid = data["issuance"]
    assert first == {
        "issued": "2026-02-21",
        "security": "Corporate Bonds",
        "method": "public",
        "amount": 150_000_000_000,
        "coupon": 3.36,
        "rating": "AA-",
        "rating_agency": "Korea Ratings, NICE Investors Service",
        "maturity": "2029-02-21",
        "redeemed": "no",
    }
    assert hybrid["issuer"] == "Samsung Display Holdings"
    assert any("1 fully redeemed issues are omitted" in note for note in data["notes"])
    assert data["source_filings"][0] == {
        "filing_number": LATEST,
        "title": "Semi-Annual Report (2026.06)",
        "filed": "2026-08-14",
        "dart_url": data["source_filings"][0]["dart_url"],
    }
    text = result.content[0].text
    assert "| Instrument | <=1y | 2-3y | Total | Public | Private |" in text
    assert "| Corporate bonds | 100,000.0 | 150,000.0 | 250,000.0 | 250,000.0 | - |" in text
    assert "Total debt securities 300,000.0; due within 1 year 150,000.0 (50.0%)." in text
    assert "AA- (Korea Ratings, NICE Investors Service)" in text
    params = upstream.params("/cprndNrdmpBlce.json")
    assert params == [{"corp_code": "00126380", "bsns_year": "2026", "reprt_code": "11012"}]
    assert all(upstream.count(path) == 1 for path in DEBT_PATHS)


@pytest.mark.anyio
async def test_detailed_debt_profile_lists_redeemed_issues_and_filed_columns(client, upstream):
    samsung(upstream)
    debt_tables(upstream)
    upstream.records(
        "/srtpdPsndbtNrdmpBlce.json",
        balance(
            "Total",
            de10_below="5,000,000,000",
            sm="5,000,000,000",
            isu_lmt="100,000,000,000",
            remndr_lmt="95,000,000,000",
        ),
    )
    result = await client.call_tool(
        "get_debt_profile", {"company": "00126380", "response_format": "detailed"}
    )
    data = result.structured_content
    assert len(data["issuance"]) == 3
    assert data["issuance"][0]["underwriter"] == "가나증권"
    assert data["issuance"][0]["issuer"] == "삼성전자㈜"
    bonds = data["ladder"][0]
    assert bonds["filed"][0] == {
        "label": "1 year or less",
        "public": 100_000_000_000,
        "total": 100_000_000_000,
    }
    short = data["ladder"][1]
    assert (short["instrument"], short["issuance_limit"], short["remaining_limit"]) == (
        "short_term_bonds",
        100_000_000_000,
        95_000_000_000,
    )
    text = result.content[0].text
    assert "### Corporate bonds as filed" in text
    assert "Short-term bond issuance limit 100,000.0, remaining 95,000.0." in text


@pytest.mark.anyio
async def test_concise_issuance_lists_the_thirty_earliest_open_issues(client, upstream):
    samsung(upstream)
    start = dt.date(2027, 1, 1)
    upstream.records(
        "/detScritsIsuAcmslt.json",
        *(
            issue(isu_mth_nm="-", mtd=(start + dt.timedelta(days=day)).strftime("%Y.%m.%d"))
            for day in range(32)
        ),
    )
    result = await client.call_tool("get_debt_profile", {"company": "005930"})
    data = result.structured_content
    assert len(data["issuance"]) == 30
    assert data["issuance"][-1]["maturity"] == "2027-01-30"
    assert any("2 later-maturing open issues are omitted" in note for note in data["notes"])
    assert (
        "| Issued | Security | Amount | Coupon | Rating | Maturity | Redeemed |"
        in result.content[0].text
    )
    detailed = await client.call_tool(
        "get_debt_profile", {"company": "005930", "response_format": "detailed"}
    )
    assert len(detailed.structured_content["issuance"]) == 32


@pytest.mark.anyio
async def test_no_debt_tables_is_an_empty_result_with_a_note(client, upstream):
    samsung(upstream)
    result = await client.call_tool("get_debt_profile", {"company": "005930"})
    data = result.structured_content
    assert data["ladder"] == []
    assert data["issuance"] == []
    assert data["derived"] == {}
    assert "fiscal_year" not in data
    assert 'no debt-security tables for "Semi-Annual Report (2026.06)"' in data["notes"][0]
    assert sum(upstream.count(path) for path in DEBT_PATHS) == 6
    assert "Note: OpenDART has no debt-security tables" in result.content[0].text


@pytest.mark.anyio
async def test_issuance_without_balances_is_noted(client, upstream):
    samsung(upstream)
    upstream.records("/detScritsIsuAcmslt.json", issue())
    result = await client.call_tool("get_debt_profile", {"company": "005930"})
    data = result.structured_content
    assert data["ladder"] == []
    assert len(data["issuance"]) == 1
    assert "No outstanding balances are reported in H1 2026." in data["notes"]


@pytest.mark.anyio
async def test_a_fiscal_year_selects_its_annual_report_without_a_search(client, upstream):
    samsung(upstream)
    debt_tables(upstream)
    result = await client.call_tool(
        "get_debt_profile", {"company": "00126380", "period": "FY", "fiscal_year": 2024}
    )
    assert result.structured_content["fiscal_year"] == 2024
    assert upstream.params("/cprndNrdmpBlce.json")[0]["reprt_code"] == "11011"
    assert upstream.count("/list.json") == 0


@pytest.mark.anyio
async def test_periods_are_probed_when_no_report_was_found(client, upstream):
    samsung(upstream)
    upstream.route("/list.json", upstream.status("013"))

    def half_year_only(request):
        if request.url.params["reprt_code"] != "11012":
            return upstream.status("013")
        return upstream.rows(balance("Total", yy1_below="10", sm="10"))

    upstream.route("/cprndNrdmpBlce.json", half_year_only)
    result = await client.call_tool("get_debt_profile", {"company": "005930"})
    data = result.structured_content
    assert (data["fiscal_year"], data["period"]) == (2026, "H1")
    assert "periods were chosen by filing deadlines" in data["notes"][0]
    assert [p["reprt_code"] for p in upstream.params("/cprndNrdmpBlce.json")] == ["11014", "11012"]


@pytest.mark.anyio
async def test_ambiguous_companies_are_errors(client):
    result = await client.call_tool(
        "get_debt_profile", {"company": "Samsung"}, raise_on_error=False
    )
    assert result.is_error
    assert "Ambiguous company" in result.content[0].text


@pytest.mark.anyio
async def test_upstream_failures_keep_their_message(client, upstream):
    samsung(upstream)
    upstream.route("/newCaplScritsNrdmpBlce.json", upstream.status("020"))
    result = await client.call_tool("get_debt_profile", {"company": "005930"}, raise_on_error=False)
    assert result.is_error
    assert "quota" in result.content[0].text


@pytest.mark.anyio
async def test_invalid_arguments_are_rejected(client):
    result = await client.call_tool(
        "get_debt_profile", {"company": "005930", "period": "Q2"}, raise_on_error=False
    )
    assert result.is_error


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    server = create_server(mcp_settings, transport=upstream.transport)
    async with Client(server) as client:
        result = await client.call_tool(
            "get_debt_profile", {"company": "00126380"}, raise_on_error=False
        )
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text
