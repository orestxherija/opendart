"""get_capital_structure over the MCP protocol: schema, sections, and errors."""

from __future__ import annotations

import pytest
from fastmcp import Client

from opendart_mcp.server import create_server

REPORT = "20260310002820"
PROFILE = {"corp_name": "삼성전자", "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD", "corp_cls": "Y"}
COUNTS = ("isu_stock_totqy", "now_to_isu_stock_totqy", "now_to_dcrs_stock_totqy", "redc")
COUNTS += ("profit_incnr", "rdmstk_repy", "etc", "istc_totqy", "tesstk_co", "distb_stock_co")
MOVES = ("stock_knd", "acqs_mth1", "acqs_mth2", "acqs_mth3", "bsis_qy", "change_qy_acqs")
MOVES += ("change_qy_dsps", "change_qy_incnr", "trmend_qy")
DIVIDEND = "Acquired within scope of profit available for dividend"
DIRECT, TRUST = "Direct acquisition", "Acquisition by trust agreement"


def periodic(**fields):
    base = {"rcept_no": REPORT, "corp_cls": "Y", "corp_code": "00126380"}
    return {**base, "corp_name": "SAMSUNG ELECTRONICS", "stlm_dt": "2025-12-31", **fields}


def shares(se, *values):
    return periodic(se=se, **dict(zip(COUNTS, values, strict=True)))


def treasury(*values, rm="-"):
    return periodic(rm=rm, **dict(zip(MOVES, values, strict=True)))


def change(when, kind, share_class, quantity, par, price):
    return periodic(
        isu_dcrs_de=when,
        isu_dcrs_stle=kind,
        isu_dcrs_stock_knd=share_class,
        isu_dcrs_qy=quantity,
        isu_dcrs_mstvdv_fval_amount=par,
        isu_dcrs_mstvdv_amount=price,
    )


def proceeds(planned_use, planned, actual_use, actual, **fields):
    row = {
        "se_nm": "유상증자",
        "tm": "-",
        "pay_de": "2025.05.30",
        "pay_amount": "-",
        "on_dclrt_cptal_use_plan": "-",
        "real_cptal_use_sttus": "-",
        "rs_cptal_use_plan_useprps": planned_use,
        "rs_cptal_use_plan_prcure_amount": planned,
        "real_cptal_use_dtls_cn": actual_use,
        "real_cptal_use_dtls_amount": actual,
        "dffrnc_occrrnc_resn": "-",
    }
    return periodic(**(row | fields))


SHARES = (
    shares(
        "보통주",
        "20,000,000,000",
        "7,780,466,850",
        "1,860,828,928",
        "-",
        "1,860,828,928",
        "-",
        "-",
        "5,919,637,922",
        "91,828,987",
        "5,827,808,935",
    ),
    shares(
        "우선주",
        "5,000,000,000",
        "1,194,671,350",
        "378,696,686",
        "-",
        "378,696,686",
        "-",
        "-",
        "815,974,664",
        "13,603,461",
        "802,371,203",
    ),
    shares(
        "Total",
        "25,000,000,000",
        "8,975,138,200",
        "2,239,525,614",
        "-",
        "2,239,525,614",
        "-",
        "-",
        "6,735,612,586",
        "105,432,448",
        "6,630,180,138",
    ),
    shares("Note", "-", "-", "-", "-", "자사주소각", "-", "-", "-", "-", "-"),
)
TREASURY = (
    treasury(
        "보통주",
        DIVIDEND,
        DIRECT,
        "Direct market acquisition",
        "29,700,000",
        "118,314,495",
        "6,040,880",
        "50,144,628",
        "91,828,987",
    ),
    treasury("우선주", DIVIDEND, TRUST, "Volume held by trustee", "-", "-", "-", "-", "-"),
    treasury("보통주", DIVIDEND, TRUST, "Subtotal", "-", "-", "-", "-", "-"),
    treasury(
        "보통주",
        "Other acquisition",
        "Other acquisition",
        "Other acquisition",
        "-",
        "-",
        "-",
        "-",
        "-",
    ),
    treasury(
        "보통주",
        "Total",
        "Total",
        "Total",
        "29,700,000",
        "118,314,495",
        "6,040,880",
        "50,144,628",
        "91,828,987",
    ),
    treasury(
        "우선주",
        "Total",
        "Total",
        "Total",
        "4,050,000",
        "16,465,497",
        "-",
        "6,912,036",
        "13,603,461",
    ),
    treasury(
        "우선주",
        DIVIDEND,
        DIRECT,
        "Direct market acquisition",
        "4,050,000",
        "16,465,497",
        "-",
        "6,912,036",
        "13,603,461",
    ),
    treasury(
        "보통주",
        DIVIDEND,
        DIRECT,
        "Subtotal",
        "29,700,000",
        "118,314,495",
        "6,040,880",
        "50,144,628",
        "91,828,987",
    ),
)
CHANGES = (
    change("-", "-", "-", "-", "-", "-"),
    change("2024.03.15", "유상증자(제3자배정)", "보통주", "1,000,000", "100", "12,500"),
    change("2025.05.31", "유상증자(일반공모)", "보통주", "11,821,000", "5,000", "140,000"),
)
PUBLIC = (
    proceeds("타법인증권 취득자금", "1,300,840,000,000", "타법인증권 취득자금", "638,139,000,000"),
    proceeds("-", "-", "운영자금", "368,540,000,000"),
    proceeds("시설자금", "354,100,000,000", "시설자금", "-", tm="2"),
)
NO_PRIVATE = periodic(
    se_nm="-",
    tm="-",
    pay_de="-",
    pay_amount="-",
    real_cptal_use_sttus="-",
    real_cptal_use_dtls_cn="-",
    real_cptal_use_dtls_amount="-",
    dffrnc_occrrnc_resn="-",
    cptal_use_plan="-",
    mtrpt_cptal_use_plan_useprps="-",
    mtrpt_cptal_use_plan_prcure_amount="-",
)


def filing(number, title):
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
    upstream.records("/list.json", filing(REPORT, "Annual Report (2025.12)"))
    upstream.records("/stockTotqySttus.json", *SHARES)
    upstream.records("/tesstkAcqsDspsSttus.json", *TREASURY)
    upstream.records("/irdsSttus.json", *CHANGES)
    upstream.records("/pssrpCptalUseDtls.json", *PUBLIC)
    upstream.records("/prvsrpCptalUseDtls.json", NO_PRIVATE)


async def call(client, **arguments):
    return await client.call_tool("get_capital_structure", arguments, raise_on_error=False)


@pytest.mark.anyio
async def test_tool_is_listed_with_its_schema_version_and_annotations(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    tool = tools["get_capital_structure"]
    assert tool.title == "Capital structure"
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False
    schema = tool.input_schema
    assert schema["required"] == ["company"]
    assert set(schema["properties"]) == {
        "company",
        "sections",
        "period",
        "fiscal_year",
        "response_format",
    }
    sections = schema["properties"]["sections"]
    assert sections["type"] == ["array", "null"]
    assert sections["minItems"] == 1
    assert sections["items"]["enum"] == [
        "shares",
        "treasury_stock",
        "capital_changes",
        "use_of_proceeds",
    ]
    assert 60 <= len(tool.description.split()) <= 120
    assert "get_corporate_events" in tool.description
    assert {"shares", "treasury_stock", "capital_changes", "use_of_proceeds"} <= set(
        tool.output_schema["properties"]
    )


@pytest.mark.anyio
async def test_every_section_from_the_latest_annual_report(client, upstream):
    samsung(upstream)
    result = await call(client, company="005930")
    assert not result.is_error
    data = result.structured_content
    assert (data["fiscal_year"], data["period"], data["period_end"]) == (2025, "FY", "2025-12-31")
    assert data["sections"] == ["shares", "treasury_stock", "capital_changes", "use_of_proceeds"]
    assert data["shares"][0] == {
        "share_class": "common",
        "authorized": 20_000_000_000,
        "issued": 5_919_637_922,
        "treasury": 91_828_987,
        "outstanding": 5_827_808_935,
    }
    assert [row["share_class"] for row in data["shares"]] == ["common", "preferred", "total"]
    assert "shares_note" not in data
    assert data["treasury_stock"] == [
        {
            "share_class": "common",
            "begin": 29_700_000,
            "acquired": 118_314_495,
            "disposed": 6_040_880,
            "retired": 50_144_628,
            "end": 91_828_987,
        },
        {
            "share_class": "preferred",
            "begin": 4_050_000,
            "acquired": 16_465_497,
            "retired": 6_912_036,
            "end": 13_603_461,
        },
    ]
    assert "treasury_stock_by_method" not in data
    assert data["capital_changes"] == [
        {
            "date": "2025-05-31",
            "kind": "유상증자(일반공모)",
            "category": "paid-in capital increase (public offering)",
            "share_class": "common",
            "shares": 11_821_000,
            "price": 140_000,
        },
        {
            "date": "2024-03-15",
            "kind": "유상증자(제3자배정)",
            "category": "paid-in capital increase (third-party allotment)",
            "share_class": "common",
            "shares": 1_000_000,
            "price": 12_500,
        },
    ]
    uses = data["use_of_proceeds"]
    assert len(uses) == 3
    assert uses[0] == {
        "offering": "public",
        "kind": "유상증자",
        "paid_on": "2025-05-30",
        "planned_use": "타법인증권 취득자금",
        "planned_amount": 1_300_840_000_000,
        "actual_use": "타법인증권 취득자금",
        "actual_amount": 638_139_000_000,
    }
    assert "series" not in uses[2]
    assert data["source_filings"][0]["filing_number"] == REPORT
    assert data["notes"] == []


@pytest.mark.anyio
async def test_text_view_renders_each_section(client, upstream):
    samsung(upstream)
    text = (await call(client, company="005930")).content[0].text
    assert text.startswith(
        "**SAMSUNG ELECTRONICS CO,.LTD (005930, KOSPI; DART 00126380): capital structure (FY2025, period end 2025-12-31)**"
    )
    assert "| Class | Authorized | Issued | Treasury | Outstanding |" in text
    assert "| Common | 20,000,000,000 | 5,919,637,922 | 91,828,987 | 5,827,808,935 |" in text
    assert "| Class | Start | Acquired | Disposed | Retired | End |" in text
    assert "| Preferred | 4,050,000 | 16,465,497 | - | 6,912,036 | 13,603,461 |" in text
    assert (
        "| 2025-05-31 | 유상증자(일반공모) | paid-in capital increase (public offering) | Common | 11,821,000 | 140,000 |"
        in text
    )
    assert (
        "| public | 유상증자 | 2025-05-30 | 타법인증권 취득자금 | 1,300,840.0 | 타법인증권 취득자금 | 638,139.0 |"
        in text
    )
    assert "Amounts in KRW million." in text
    assert "Difference reason" not in text


@pytest.mark.anyio
async def test_detailed_adds_history_methods_par_values_and_series(client, upstream):
    samsung(upstream)
    result = await call(client, company="005930", response_format="detailed")
    data = result.structured_content
    assert data["shares"][0]["retired_from_profits"] == 1_860_828_928
    assert data["shares_note"] == "retired from profits: 자사주소각"
    methods = data["treasury_stock_by_method"]
    assert [row["share_class"] for row in methods] == ["common", "preferred"]
    assert methods[0]["method"] == f"{DIVIDEND} > {DIRECT} > Direct market acquisition"
    assert data["capital_changes"][0]["par_value"] == 5_000
    assert data["use_of_proceeds"][2]["series"] == "2"
    text = result.content[0].text
    assert "Share-count note: retired from profits: 자사주소각" in text
    assert "### Treasury stock by method" in text
    assert "| Decreased to date | Retired from profits |" in text
    assert "Capital reduction" not in text


@pytest.mark.anyio
async def test_sections_limit_the_output_and_the_upstream_calls(client, upstream):
    samsung(upstream)
    result = await call(client, company="005930", sections=["treasury_stock"])
    data = result.structured_content
    assert data["sections"] == ["treasury_stock"]
    assert "shares" not in data
    assert "capital_changes" not in data
    assert "use_of_proceeds" not in data
    assert len(data["treasury_stock"]) == 2
    assert upstream.count("/irdsSttus.json") == 0
    assert upstream.count("/pssrpCptalUseDtls.json") == 0
    assert upstream.count("/stockTotqySttus.json") == 1
    assert "### Shares" not in result.content[0].text


@pytest.mark.anyio
async def test_requested_sections_without_rows_say_so(client, upstream):
    samsung(upstream)
    upstream.records(
        "/pssrpCptalUseDtls.json",
        PUBLIC[1]
        | {"real_cptal_use_dtls_cn": "-", "real_cptal_use_dtls_amount": "-", "pay_de": "-"},
    )
    result = await call(client, company="005930", sections=["use_of_proceeds", "shares"])
    data = result.structured_content
    assert data["sections"] == ["shares", "use_of_proceeds"]
    assert data["use_of_proceeds"] == []
    text = result.content[0].text
    assert "### Use of proceeds\nNone filed in this report." in text
    assert "Amounts in KRW million." not in text


@pytest.mark.anyio
async def test_no_data_is_an_empty_result_with_notes(client, upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    result = await call(client, company="005930", sections=["shares", "capital_changes"])
    assert not result.is_error
    data = result.structured_content
    assert data["shares"] == data["capital_changes"] == []
    assert "treasury_stock" not in data
    assert "fiscal_year" not in data
    assert any(
        note.startswith("No periodic report for Q3 2026, H1 2026, Q1 2026")
        for note in data["notes"]
    )
    assert "None filed in this report." in result.content[0].text


@pytest.mark.anyio
async def test_ambiguous_names_return_candidates(client):
    result = await call(client, company="Samsung")
    assert result.is_error
    assert "Ambiguous company" in result.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize("sections", [[], ["dilution"]])
async def test_schema_rejects_bad_sections(client, upstream, sections):
    result = await call(client, company="005930", sections=sections)
    assert result.is_error
    assert upstream.count() == upstream.count("/corpCode.xml")


@pytest.mark.anyio
async def test_periods_before_2015_are_rejected_by_the_schema(client):
    result = await call(client, company="005930", fiscal_year=2014)
    assert result.is_error


@pytest.mark.anyio
async def test_upstream_failures_are_explained(client, upstream):
    samsung(upstream)
    upstream.route("/stockTotqySttus.json", upstream.status("800"))
    result = await call(client, company="005930")
    assert result.is_error
    assert "maintenance" in result.content[0].text


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    async with Client(create_server(mcp_settings, transport=upstream.transport)) as client:
        result = await call(client, company="00126380")
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text


@pytest.mark.anyio
async def test_unknown_companies_point_to_find_company(client):
    result = await call(client, company="999999")
    assert result.is_error
    assert "find_company" in result.content[0].text


@pytest.mark.anyio
async def test_periods_that_have_not_ended_are_rejected(client, upstream):
    samsung(upstream)
    result = await call(client, company="005930", period="FY", fiscal_year=2026)
    assert result.is_error
    assert "No FY 2026 period is available" in result.content[0].text
    assert upstream.count("/stockTotqySttus.json") == 0
