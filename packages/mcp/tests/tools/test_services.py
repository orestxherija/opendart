"""list_services and call_service, the escape hatches, over the MCP protocol."""

from __future__ import annotations

import pytest
from fastmcp import Client

from opendart_analysis.catalog import SERVICES
from opendart_mcp.server import create_server
from opendart_mcp.services.catalog import COVERAGE
from opendart_mcp.services.catalog_params import param_shapes
from opendart_mcp.settings import ToolSettings

PROFILE = {"corp_name": "삼성전자", "corp_cls": "Y", "acc_mt": "12", "stock_code": "005930"}


def bond(number, face, *, price="71,500", rate="1.5"):
    return {
        "rcept_no": number,
        "corp_cls": "Y",
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "bd_tm": "12",
        "bd_knd": "무기명식 무보증 사모 전환사채",
        "bd_fta": face,
        "bd_intr_ex": rate,
        "cv_prc": price,
        "sbd": "2025.03.10",
        "ovis_fta": "-",
        "atcsc_rmislmt": "미정",
    }


@pytest.fixture
def hatch_server(mcp_settings, sdk_settings, upstream, now):
    settings = mcp_settings.model_copy(update={"tools": ToolSettings(enable_service_tools=True)})
    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/company.json", upstream.ok(**PROFILE))
    return create_server(
        settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )


@pytest.fixture
async def hatch(hatch_server):
    async with Client(hatch_server) as connected:
        yield connected


async def call(client, params, *, service="cvbd_is_decsn", **arguments):
    return await client.call_tool(
        "call_service", {"service": service, "params": params, **arguments}, raise_on_error=False
    )


@pytest.mark.anyio
async def test_the_escape_hatch_is_off_by_default(client):
    names = {tool.name for tool in await client.list_tools()}
    assert not names & {"list_services", "call_service"}


@pytest.mark.anyio
async def test_enabled_tools_come_last_with_versions_and_annotations(hatch):
    tools = await hatch.list_tools()
    assert [tool.name for tool in tools[-2:]] == ["list_services", "call_service"]
    listing, caller = tools[-2:]
    for tool in (listing, caller):
        assert tool.meta is not None
        assert tool.meta["fastmcp"]["version"] == "1.0.0"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False
        assert "last resort" in (tool.description or "")
    assert caller.input_schema["required"] == ["service"]
    assert {"params", "response_format", "limit", "page"} <= set(caller.input_schema["properties"])
    assert caller.output_schema is not None
    assert {"tables", "pagination", "params"} <= set(caller.output_schema["properties"])
    assert "required" not in listing.input_schema


@pytest.mark.anyio
async def test_list_services_finds_a_service_and_its_covering_tool(hatch, upstream):
    result = await hatch.call_tool("list_services", {"query": "convertible bond", "limit": 3})
    data = result.structured_content
    first = data["services"][0]
    assert first["service"] == "cvbd_is_decsn"
    assert first["covered_by"] == "get_corporate_events (kind convertible_bond)"
    params = {p["wire"]: p for p in first["params"]}
    assert params["corp_code"]["accepts"].startswith("company name")
    assert params["bgn_de"]["required"] is True
    assert len(data["services"]) == 3
    assert data["total"] >= 3
    text = result.content[0].text
    assert '**OpenDART services matching "convertible bond"** (3 of' in text
    assert "corp_code* (company name, stock code, or 8-digit corp code)" in text
    assert upstream.count("/cvbdIsDecsn.json") == 0


@pytest.mark.anyio
async def test_list_services_without_a_query_lists_every_callable_service(hatch):
    result = await hatch.call_tool("list_services", {"limit": 85})
    data = result.structured_content
    names = [s["service"] for s in data["services"]]
    assert data["total"] == len(names) == len(SERVICES) - 3
    assert not {"document", "corporation_codes", "fnltt_xbrl"} & set(names)
    search = next(s for s in data["services"] if s["service"] == "search")
    accepts = {p["wire"]: p["accepts"] for p in search["params"]}
    assert accepts["page_no"] == "whole number"
    assert accepts["sort_mth"] == "one of asc, desc"
    assert accepts["pblntf_detail_ty"].endswith("codes)")
    assert "available to call_service" in result.content[0].text


@pytest.mark.anyio
async def test_list_services_explains_when_nothing_matches(hatch):
    result = await hatch.call_tool("list_services", {"query": "zzzz qqqq"})
    data = result.structured_content
    assert data["services"] == []
    assert data["total"] == 0
    assert "No service matches 'zzzz qqqq'" in data["notes"][0]


@pytest.mark.anyio
async def test_call_service_resolves_names_and_dates_and_normalizes(hatch, upstream):
    upstream.records(
        "/cvbdIsDecsn.json",
        bond("20250310000123", "100,000,000,000"),
        bond("20250611000456", "50,000,000,000", price="80,000", rate="0.5"),
    )
    params = {"company": "Samsung Electronics", "since": "2025-01-01", "until": "20251231"}
    result = await call(hatch, params)
    data = result.structured_content
    assert data["params"] == {"corp_code": "00126380", "bgn_de": "20250101", "end_de": "20251231"}
    assert upstream.params("/cvbdIsDecsn.json") == [data["params"]]
    (table,) = data["tables"]
    labels = [column["label"] for column in table["columns"]]
    assert table["common"]["Corporation type"] == "KOSPI"
    assert table["common"]["Date of subscription"] == "2025-03-10"
    face = labels.index(next(label for label in labels if "face" in label.casefold()))
    assert [row[face] for row in table["rows"]] == [100_000_000_000, 50_000_000_000]
    kinds = {column["name"]: column["kind"] for column in table["columns"]}
    assert kinds["bd_fta"] == "amount"
    assert kinds["cv_prc"] == "per_share"
    assert "ovis_fta" not in kinds
    assert table["common"]["Unissued amount relative to the Article(KRW)"] == "미정"
    assert "raw" not in table
    assert data["notes"][0].startswith("Resolved 'Samsung Electronics' to")
    assert [f["filing_number"] for f in data["source_filings"]] == [
        "20250310000123",
        "20250611000456",
    ]
    assert data["pagination"] == {"total": 2, "page": 1, "limit": 20, "has_more": False}
    text = result.content[0].text
    assert "**cvbd_is_decsn: Decision on Issuance of Convertible Bonds**" in text
    assert "100,000,000,000" in text
    assert "Amounts are exact won" in text


@pytest.mark.anyio
async def test_detailed_output_keeps_every_field_and_the_upstream_text(hatch, upstream):
    upstream.records("/cvbdIsDecsn.json", bond("20250310000123", "100,000,000,000"))
    params = {"corp_code": "00126380", "bgn_de": "30d", "end_de": "today"}
    result = await call(hatch, params, response_format="detailed")
    (table,) = result.structured_content["tables"]
    names = [column["name"] for column in table["columns"]]
    assert names[:4] == [
        "filing_number",
        "corporation_type",
        "corporation_code",
        "corporation_name",
    ]
    assert "ovis_fta" in names
    assert "common" not in table
    row, raw = table["rows"][0], table["raw"][0]
    assert raw[names.index("bd_fta")] == "100,000,000,000"
    assert row[names.index("bd_fta")] == 100_000_000_000
    assert row[names.index("ovis_fta")] is None
    assert row[names.index("bd_intr_ex")] == 1.5
    assert result.structured_content["params"]["bgn_de"] == "20260922"
    assert result.structured_content["notes"] == []


@pytest.mark.anyio
async def test_registration_statement_sections_become_separate_tables(hatch, upstream):
    general = {"rcept_no": "20250501000777", "corp_cls": "Y", "sbd": "20250520", "exprc": "-"}
    shares = {"rcept_no": "20250501000777", "stksen": "보통주", "stkcnt": "1,000,000"}
    upstream.route(
        "/estkRs.json",
        upstream.ok(
            group=[
                {"title": "일반사항", "list": [general]},
                {"title": "증권의종류", "list": [shares]},
                {"title": "인수인정보", "list": []},
            ]
        ),
    )
    params = {"corp_code": "00126380", "bgn_de": "2025-01-01", "end_de": "2025-12-31"}
    result = await call(hatch, params, service="AE00078")
    data = result.structured_content
    assert data["service"] == "estk_rs"
    assert [table["section"] for table in data["tables"]] == ["일반사항", "증권의종류"]
    first = {column["name"]: column for column in data["tables"][0]["columns"]}
    assert first["sbd"]["kind"] == "date"
    assert data["tables"][0]["rows"][0][list(first).index("sbd")] == "2025-05-20"
    second = data["tables"][1]
    assert second["rows"][0][[c["name"] for c in second["columns"]].index("stkcnt")] == 1_000_000
    assert "### 일반사항" in result.content[0].text


@pytest.mark.anyio
async def test_nested_records_carry_their_parents_values(hatch, upstream):
    director = {
        "nm": "홍길동",
        "ofcps": "대표이사",
        "mendng_totamt": "1,200,000,000",
        "list": [
            {"stk_bsd_pd_mendng_totamt_knd": "RSU", "stk_bsd_pd_mendng_totamt_qty": "1,000"},
            {"stk_bsd_pd_mendng_totamt_knd": "PSU", "stk_bsd_pd_mendng_totamt_qty": "500"},
        ],
    }
    lone = {"nm": "김철수", "ofcps": "사내이사", "mendng_totamt": "900,000,000", "list": []}
    upstream.route(
        "/hmvAuditIndvdlBySttusV2.json",
        upstream.ok(rcept_no="20260310000789", stlm_dt="2025.12.31", group=[director, lone]),
    )
    params = {"corp_code": "00126380", "bsns_year": 2025, "reprt_code": "FY"}
    result = await call(hatch, params, service="hmv_audit_indvdl_by_sttus_v2")
    data = result.structured_content
    assert data["params"] == {"corp_code": "00126380", "bsns_year": "2025", "reprt_code": "11011"}
    (table,) = data["tables"]
    names = [column["name"] for column in table["columns"]]
    assert len(table["rows"]) == 3
    assert [row[names.index("nm")] for row in table["rows"]] == ["홍길동", "홍길동", "김철수"]
    assert table["rows"][2][names.index("mendng_totamt")] == 900_000_000
    assert table["common"]["Settlement date"] == "2025-12-31"
    assert data["source_filings"][0]["filing_number"] == "20260310000789"


@pytest.mark.anyio
async def test_the_company_overview_is_one_row(hatch, upstream):
    result = await call(hatch, {"corp_code": "005930"}, service="company")
    data = result.structured_content
    assert data["params"] == {"corp_code": "00126380"}
    (table,) = data["tables"]
    names = [column["name"] for column in table["columns"]]
    assert dict(zip(names, table["rows"][0], strict=True)) == {
        "corporation_name": "삼성전자",
        "stock_code": "005930",
        "corporation_type": "KOSPI",
        "acc_mt": "12",
    }


@pytest.mark.anyio
@pytest.mark.parametrize("codes", [["Samsung Electronics", "000660"], "Samsung Electronics,000660"])
async def test_list_parameters_accept_names_and_codes(hatch, upstream, codes):
    upstream.records(
        "/fnlttMultiAcnt.json",
        {"rcept_no": "20260310000789", "stock_code": "005930", "account_nm": "매출액"},
        {"rcept_no": "20260311000111", "stock_code": "000660", "account_nm": "매출액"},
    )
    params = {"corp_code": codes, "bsns_year": "2025", "reprt_code": "11011"}
    result = await call(hatch, params, service="fnltt_multi_acnt")
    sent = upstream.params("/fnlttMultiAcnt.json")[0]
    assert sent == {"corp_code": "00126380,00164779", "bsns_year": "2025", "reprt_code": "11011"}
    assert result.structured_content["params"]["corp_code"] == ["00126380", "00164779"]


MULTI = {"bsns_year": "2025", "reprt_code": "FY"}
REVENUE = {"rcept_no": "20260310000789", "stock_code": "005930", "account_nm": "매출액"}


@pytest.mark.anyio
async def test_official_names_with_commas_stay_whole_in_a_company_string(hatch, upstream):
    upstream.records("/fnlttMultiAcnt.json", REVENUE)
    names = "SAMSUNG ELECTRONICS CO,.LTD, Celltrion, Inc.; LG ENERGY SOLUTION, LTD."
    result = await call(hatch, {"companies": names, **MULTI}, service="fnltt_multi_acnt")
    data = result.structured_content
    assert data["params"]["corp_code"] == ["00126380", "00413046", "01515323"]
    assert data["notes"][0].startswith("Resolved 'SAMSUNG ELECTRONICS CO,.LTD' to")
    assert data["notes"][1].startswith("Resolved 'Celltrion, Inc.' to")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("companies", "count"),
    [(["005930"] * 101, 101), (",".join(["Samsung Electronics"] * 150), 150), ([" "], 0)],
    ids=["list", "string", "blank"],
)
async def test_company_lists_are_bounded_before_any_company_is_resolved(
    hatch, upstream, companies, count
):
    result = await call(hatch, {"companies": companies, **MULTI}, service="fnltt_multi_acnt")
    assert result.is_error
    message = f"corp_code takes 1 to 100 companies per call; got {count}. Split a longer list"
    assert message in result.content[0].text
    assert upstream.count("/company.json") == 0
    assert upstream.count("/fnlttMultiAcnt.json") == 0


@pytest.mark.anyio
async def test_a_list_of_100_companies_is_sent_whole(hatch, upstream):
    upstream.records("/fnlttMultiAcnt.json", REVENUE)
    codes = ["00126380"] * 100
    result = await call(hatch, {"corp_code": codes, **MULTI}, service="fnltt_multi_acnt")
    assert not result.is_error
    assert upstream.params("/fnlttMultiAcnt.json")[0]["corp_code"] == ",".join(codes)


@pytest.mark.anyio
async def test_rows_are_paged_locally_and_upstream_pages_are_noted(hatch, upstream):
    filings = [
        {"rcept_no": f"2026102200000{i}", "report_nm": f"Report {i}", "corp_name": "삼성전자"}
        for i in range(5)
    ]
    upstream.records("/list.json", *filings, page_no=1, page_count=5, total_count=12, total_page=3)
    params = {"corp_code": "00126380", "page_count": "5", "sort_mth": "DESC"}
    first = (await call(hatch, params, service="search", limit=2)).structured_content
    paging = first["pagination"]
    assert paging["has_more"] is True
    assert paging["next_call"]["arguments"]["page"] == 2
    assert any("page_no" in note for note in first["notes"])
    assert first["source_filings"][0]["title"] == "Report 0"
    assert upstream.params("/list.json")[0] == {
        "corp_code": "00126380",
        "page_count": "5",
        "sort_mth": "desc",
    }
    arguments = paging["next_call"]["arguments"]
    second = await hatch.call_tool("call_service", arguments)
    assert second.structured_content["pagination"]["page"] == 2
    assert "Rows 3-4 of 5. Next: call_service with page=3." in second.content[0].text
    assert upstream.count("/list.json") == 1


@pytest.mark.anyio
async def test_no_data_is_an_empty_result_with_a_note(hatch, upstream):
    params = {"corp_code": "00126380", "bgn_de": "2025-01-01", "end_de": "2025-12-31"}
    result = await call(hatch, params, service="dfOcr")
    data = result.structured_content
    assert data["tables"] == []
    assert data["notes"] == ["OpenDART has no data for these parameters (status 013)."]
    assert data["pagination"]["total"] == 0
    assert "Amounts are exact won" not in result.content[0].text


DATES = {"bgn_de": "2025-01-01", "end_de": "2025-12-31"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("service", "params", "expected"),
    [
        ("cvbd_is_decsn_x", {}, "did you mean cvbd_is_decsn"),
        ("document", {"rcept_no": "20250310000123"}, "use read_filing instead"),
        ("cvbd_is_decsn", {"corp_code": "00126380", "bogus": "1", **DATES}, "no parameter 'bogus'"),
        ("cvbd_is_decsn", {"corp_code": "00126380"}, "requires bgn_de, end_de"),
        (
            "cvbd_is_decsn",
            {"corp_code": "00126380", "company": "Samsung", **DATES},
            "given twice",
        ),
        ("cvbd_is_decsn", {"corp_code": "00126380", "bgn_de": "soon", "end_de": "today"}, "bgn_de"),
        ("cvbd_is_decsn", {"corp_code": ["00126380"], **DATES}, "takes one value"),
        ("alot_matter", {"corp_code": "00126380", "bsns_year": "2014", "reprt_code": "FY"}, "2015"),
        ("alot_matter", {"corp_code": "00126380", "bsns_year": 2025, "reprt_code": "Q2"}, "FY, H1"),
        (
            "fnltt_singl_acnt_all",
            {"corp_code": "00126380", "bsns_year": 2025, "reprt_code": "FY", "fs_div": "XFS"},
            "must be one of OFS, CFS",
        ),
        ("search", {"page_no": "two"}, "whole number"),
        ("search", {"page_no": "\u00b2"}, "whole number"),
        (
            "alot_matter",
            {"corp_code": "00126380", "bsns_year": "\u00b2\u00b2\u00b2\u00b2", "reprt_code": "FY"},
            "2015",
        ),
        ("cvbd_is_decsn", {"corp_code": "Samsung", **DATES}, "Ambiguous company"),
    ],
)
async def test_invalid_calls_explain_the_fix(hatch, upstream, service, params, expected):
    result = await call(hatch, params, service=service)
    assert result.is_error
    assert expected in result.content[0].text
    assert upstream.count("/cvbdIsDecsn.json") == 0


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    settings = mcp_settings.model_copy(update={"tools": ToolSettings(enable_service_tools=True)})
    async with Client(create_server(settings, transport=upstream.transport)) as client:
        listed = await client.call_tool("list_services", {"query": "dividend"})
        result = await call(client, {"corp_code": "00126380", **DATES})
    assert listed.structured_content["services"][0]["service"] == "alot_matter"
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text
    assert upstream.count() == 0


def test_every_service_parameter_has_an_sdk_type():
    for name, spec in SERVICES.items():
        shapes = param_shapes(name)
        assert set(shapes) == {param.name for param in spec.params}
    assert param_shapes("fnltt_multi_acnt")["corporation_codes"].many
    assert param_shapes("search")["page_size"].integer


def test_every_service_except_the_taxonomy_names_its_covering_tool():
    assert set(COVERAGE) <= set(SERVICES)
    assert set(SERVICES) - set(COVERAGE) == {"xbrl_taxonomy"}
