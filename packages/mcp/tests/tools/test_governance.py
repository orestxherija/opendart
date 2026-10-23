"""get_governance over the MCP protocol: schema, audit and board sections, flags, and errors."""

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
PRIOR = "20250311001111"
OPINIONS = "/accnutAdtorNmNdAdtOpinion.json"
FEES = "/adtServcCnclsSttus.json"
NON_AUDIT = "/accnutAdtorNonAdtServcCnclsSttus.json"
BOARD = "/outcmpnyDrctrNdChangeSttus.json"
OTHER_PATHS = (
    "/exctvSttus.json",
    "/empSttus.json",
    "/hmvAuditAllSttus.json",
    "/indvdlByPayV2.json",
    "/hmvAuditIndvdlBySttusV2.json",
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


def samsung(upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    upstream.records(
        "/list.json",
        report("20260814001234", "Semi-Annual Report (2026.06)"),
        report(ANNUAL, "Annual Report (2025.12)"),
    )


def opinion(term, auditor="가나회계법인", filed="적정의견", number=ANNUAL, **fields):
    record = {
        "rcept_no": number,
        "bsns_year": term,
        "adtor": auditor,
        "adt_opinion": filed,
        "adt_reprt_spcmnt_matter": "-",
        "emphs_matter": "해당사항 없음",
        "core_adt_matter": "1. 매출 인식\n2. 재고자산 평가",
        "stlm_dt": "2025-12-31",
    }
    return record | fields


def fee(term, contract, hours):
    return {
        "rcept_no": ANNUAL,
        "bsns_year": term,
        "adtor": "가나회계법인",
        "cn": "분ㆍ반기 검토\n연결 감사",
        "mendng": "-",
        "tot_reqre_time": "-",
        "adt_cntrct_dtls_mendng": contract,
        "adt_cntrct_dtls_time": hours,
        "real_exc_dtls_mendng": contract,
        "real_exc_dtls_time": hours,
    }


def audit_tables(upstream, *opinions):
    upstream.records(
        OPINIONS,
        *(
            opinions
            or (
                opinion("제57기 \n(당기)"),
                opinion("제57기 \n(당기)"),
                opinion("제56기\n(전기)"),
                opinion("제55기\n(전전기)"),
            )
        ),
    )
    upstream.records(
        FEES, fee("제57기\n(당기)", "8,100", "81,000"), fee("제56기\n(당기)", "7,800", "78,000")
    )
    upstream.records(
        NON_AUDIT,
        {
            "rcept_no": ANNUAL,
            "bsns_year": "제57기(당기)",
            "cntrct_cncls_de": "-",
            "servc_cn": "-",
            "servc_exc_pd": "-",
            "servc_mendng": "-",
            "rm": "-",
        },
        {
            "rcept_no": ANNUAL,
            "bsns_year": "제56기(전기)",
            "cntrct_cncls_de": "2017.02",
            "servc_cn": "세무자문",
            "servc_exc_pd": "2024.01~2024.06",
            "servc_mendng": "43",
            "rm": "가나회계법인",
        },
    )
    upstream.records(
        BOARD,
        {
            "rcept_no": ANNUAL,
            "drctr_co": "10",
            "otcmp_drctr_co": "6",
            "apnt": "2",
            "rlsofc": "0",
            "mdstrm_resig": "0",
        },
    )


@pytest.mark.anyio
async def test_governance_is_listed_with_schema_version_and_annotations(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    tool = tools["get_governance"]
    assert tool.meta is not None
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    properties = tool.input_schema["properties"]
    assert list(properties) == ["company", "sections", "fiscal_year", "period", "response_format"]
    assert properties["sections"]["default"] == ["audit", "board"]
    assert properties["sections"]["items"]["enum"] == [
        "audit",
        "board",
        "executives",
        "compensation",
        "employees",
    ]
    assert properties["period"]["default"] == "FY"
    assert tool.output_schema is not None
    assert {"audit", "board", "flags", "sections"} <= set(tool.output_schema["properties"])
    assert 60 <= len((tool.description or "").split()) <= 120


@pytest.mark.anyio
async def test_default_sections_read_audit_and_board_only(client, upstream):
    samsung(upstream)
    audit_tables(upstream)
    result = await client.call_tool("get_governance", {"company": "005930"})
    data = result.structured_content
    assert (data["fiscal_year"], data["period"], data["sections"]) == (
        2025,
        "FY",
        ["audit", "board"],
    )
    audit = data["audit"]
    assert (audit["auditor"], audit["opinion"], audit["opinion_as_filed"]) == (
        "가나회계법인",
        "unqualified",
        "적정의견",
    )
    assert "emphasis" not in audit
    assert audit["key_audit_matters"] == ["매출 인식", "재고자산 평가"]
    assert (audit["prior_auditor"], audit["auditor_changed_vs_prior_year"]) == (
        "가나회계법인",
        False,
    )
    assert audit["fee_scale"] == 1_000_000
    assert audit["fees"][0] == {
        "fiscal_year": 2025,
        "auditor": "가나회계법인",
        "contract_fee": 8_100_000_000,
        "contract_hours": 81000,
        "actual_fee": 8_100_000_000,
        "actual_hours": 81000,
    }
    assert audit["fees"][1]["fiscal_year"] == 2024
    assert audit["non_audit_services"] == []
    assert "history" not in audit
    assert data["board"] == {
        "directors": 10,
        "outside_directors": 6,
        "outside_director_pct": 60.0,
        "outside_appointed": 2,
        "outside_dismissed": 0,
        "outside_resigned_early": 0,
    }
    assert data["flags"] == []
    assert any("KRW million per filed unit" in note for note in data["notes"])
    params = upstream.params(OPINIONS)
    assert params == [{"corp_code": "00126380", "bsns_year": "2025", "reprt_code": "11011"}]
    assert all(upstream.count(path) == 0 for path in OTHER_PATHS)
    text = result.content[0].text
    assert (
        "Auditor: 가나회계법인; prior year 가나회계법인. Opinion: unqualified (적정의견)." in text
    )
    assert "1. 매출 인식" in text
    assert "| 2025 | 가나회계법인 | 8,100.0 | 81,000 | 8,100.0 | 81,000 |" in text
    assert "Directors: 10; outside directors: 6 (60.0%)." in text


@pytest.mark.anyio
async def test_flags_report_modified_opinions_going_concern_and_auditor_changes(client, upstream):
    samsung(upstream)
    audit_tables(
        upstream,
        opinion(
            "제57기(당기)", filed="한정의견", emphs_matter="계속기업 가정에 관한 중요한 불확실성"
        ),
        opinion("제56기(전기)", auditor="다라회계법인"),
    )
    result = await client.call_tool("get_governance", {"company": "005930"})
    flags = result.structured_content["flags"]
    assert [flag["kind"] for flag in flags] == [
        "modified_opinion",
        "going_concern",
        "auditor_change",
    ]
    assert flags[0]["detail"] == "Qualified opinion for FY2025, filed as 한정의견."
    assert flags[2]["detail"] == "Auditor changed from 다라회계법인 to 가나회계법인."
    text = result.content[0].text
    assert "### Flags" in text
    assert "- going_concern: Going-concern language in the FY2025 audit report" in text


@pytest.mark.anyio
async def test_the_prior_auditor_costs_one_extra_call_when_missing(client, upstream):
    samsung(upstream)
    audit_tables(upstream)

    def by_year(request):
        if request.url.params["bsns_year"] == "2024":
            return upstream.rows(opinion("제56기(당기)", auditor="라마회계법인", number=PRIOR))
        return upstream.rows(opinion("제57기(당기)", core_adt_matter="-"))

    upstream.route(OPINIONS, by_year)
    result = await client.call_tool("get_governance", {"company": "005930", "sections": ["audit"]})
    data = result.structured_content
    assert data["audit"]["key_audit_matters"] == []
    assert "Key audit matters" not in result.content[0].text
    assert (data["audit"]["prior_auditor"], data["audit"]["auditor_changed_vs_prior_year"]) == (
        "라마회계법인",
        True,
    )
    assert [flag["kind"] for flag in data["flags"]] == ["auditor_change"]
    assert [p["bsns_year"] for p in upstream.params(OPINIONS)] == ["2025", "2024"]
    assert [s["filing_number"] for s in data["source_filings"]] == [ANNUAL, PRIOR]
    assert "board" not in data
    assert upstream.count(BOARD) == 0


@pytest.mark.anyio
async def test_detailed_audit_keeps_history_and_prior_services(client, upstream):
    samsung(upstream)
    audit_tables(upstream)
    result = await client.call_tool(
        "get_governance",
        {"company": "005930", "sections": ["audit", "audit"], "response_format": "detailed"},
    )
    data = result.structured_content
    assert data["sections"] == ["audit"]
    audit = data["audit"]
    assert [year["fiscal_year"] for year in audit["history"]] == [2025, 2024, 2023]
    assert audit["fees"][0]["scope"] == "분ㆍ반기 검토 연결 감사"
    assert audit["non_audit_services"] == [
        {
            "fiscal_year": 2024,
            "contracted": "2017.02",
            "service": "세무자문",
            "period": "2024.01~2024.06",
            "fee": 43_000_000,
            "note": "가나회계법인",
        }
    ]
    text = result.content[0].text
    assert "### Non-audit services" in text
    assert "### Opinion history" in text


@pytest.mark.anyio
async def test_sections_without_data_are_noted(client, upstream):
    samsung(upstream)
    upstream.records(BOARD, {"rcept_no": ANNUAL, "drctr_co": "7", "otcmp_drctr_co": "3"})
    result = await client.call_tool("get_governance", {"company": "005930"})
    data = result.structured_content
    assert "audit" not in data
    assert data["board"]["outside_director_pct"] == 42.9
    assert "No audit data in the FY2025 report." in data["notes"]
    assert data["flags"] == []


@pytest.mark.anyio
async def test_flags_need_the_audit_section(client, upstream):
    samsung(upstream)
    audit_tables(upstream)
    result = await client.call_tool("get_governance", {"company": "005930", "sections": ["board"]})
    data = result.structured_content
    assert "Flags come from the audit section, which was not requested." in data["notes"]
    assert upstream.count(OPINIONS) == 0


@pytest.mark.anyio
async def test_no_tables_is_an_empty_result_with_a_note(client, upstream):
    samsung(upstream)
    result = await client.call_tool(
        "get_governance", {"company": "005930", "fiscal_year": 2023, "period": "H1"}
    )
    data = result.structured_content
    assert data["flags"] == []
    assert "audit" not in data
    assert data["notes"] == ["OpenDART has no audit, board tables for H1 2023."]
    assert upstream.params(BOARD)[0] == {
        "corp_code": "00126380",
        "bsns_year": "2023",
        "reprt_code": "11012",
    }


@pytest.mark.anyio
async def test_invalid_sections_are_rejected(client):
    result = await client.call_tool(
        "get_governance", {"company": "005930", "sections": ["pay"]}, raise_on_error=False
    )
    assert result.is_error
    empty = await client.call_tool(
        "get_governance", {"company": "005930", "sections": []}, raise_on_error=False
    )
    assert empty.is_error


@pytest.mark.anyio
async def test_future_periods_are_explained(client, upstream):
    samsung(upstream)
    result = await client.call_tool(
        "get_governance", {"company": "005930", "fiscal_year": 2027}, raise_on_error=False
    )
    assert result.is_error
    assert "has not ended yet" in result.content[0].text
