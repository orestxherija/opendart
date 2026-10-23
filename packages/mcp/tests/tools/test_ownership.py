"""get_ownership over the MCP protocol: schema, snapshot, holding reports, and errors."""

from __future__ import annotations

import pytest
from fastmcp import Client

from opendart_mcp.server import create_server

REPORT = "20260310002820"
PROFILE = {
    "corp_name": "삼성전자",
    "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
    "stock_code": "005930",
    "corp_cls": "Y",
    "acc_mt": "12",
}

# Samsung Electronics' FY2025 annual report and holding reports, as OpenDART returned them.
# Holders: class|name|relation|shares at start|% at start|shares at end|% at end|note.
HOLDER_TABLE = """
보통주|삼성생명보험㈜|최대주주 본인|508,157,148|8.51|503,904,843|8.51|시간외매매
보통주|홍라희|최대주주의 특수관계인|97,978,700|1.64|87,978,700|1.49|시간외매매
우선주|홍라희|최대주주의 특수관계인|206,633|0.03|206,633|0.03|-
보통주|이재용|최대주주의 특수관계인|97,414,196|1.63|97,414,196|1.65|-
우선주|이재용|최대주주의 특수관계인|137,757|0.02|137,757|0.02|-
보통주|이부진|계열회사 임원|47,745,681|0.80|41,745,681|0.71|시간외매매
우선주|이부진|계열회사 임원|137,755|0.02|137,755|0.02|-
보통주|이서현|계열회사 임원|47,290,190|0.79|45,574,190|0.77|시간외매매
우선주|이서현|계열회사 임원|137,755|0.02|137,755|0.02|-
보통주|전영현|계열회사 임원|0|0.00|17,000|0.00|신규 선임
보통주|노태문|계열회사 임원|28,000|0.00|50,679|0.00|자사주 상여금
우선주|삼성생명보험㈜|최대주주 본인|43,950|0.01|43,950|0.01|-
보통주|송재혁|계열회사 임원|0|0.00|13,373|0.00|신규 선임
보통주|조혜경|계열회사 임원|500|0.00|500|0.00|-
보통주|이혁재|계열회사 임원|0|0.00|200|0.00|신규 선임
보통주|한종희|계열회사 임원|25,000|0.00|0|0.00|이사 퇴임
보통주|이정배|계열회사 임원|21,800|0.00|0|0.00|이사 임기만료
보통주|김한조|계열회사 임원|6,985|0.00|0|0.00|이사 임기만료
보통주|삼성생명보험㈜\\n(특별계정)|최대주주 본인|5,378,652|0.09|4,424,328|0.07|장내 매매
우선주|삼성생명보험㈜\\n(특별계정)|최대주주 본인|329,788|0.04|159,926|0.02|장내 매매
보통주|삼성물산㈜|계열회사|298,818,100|5.01|298,818,100|5.05|-
보통주|삼성화재해상보험㈜|계열회사|88,802,052|1.49|88,058,948|1.49|시간외매매
보통주|삼성복지재단|출연 재단|4,484,150|0.08|4,484,150|0.08|-
보통주|삼성문화재단|출연 재단|1,880,750|0.03|1,880,750|0.03|-
보통주|삼성생명공익재단|출연 재단|1,250|0.00|1,250|0.00|-
보통주|Total||1,198,033,154|20.07|1,174,366,888|19.84|-
우선주|Total||993,638|0.12|823,776|0.10|-
"""
# Share counts: class, then the ten count columns in COUNTS order.
SHARE_TABLE = """
보통주|20,000,000,000|7,780,466,850|1,860,828,928|-|1,860,828,928|-|-|5,919,637,922|91,828,987|5,827,808,935
우선주|5,000,000,000|1,194,671,350|378,696,686|-|378,696,686|-|-|815,974,664|13,603,461|802,371,203
Total|25,000,000,000|8,975,138,200|2,239,525,614|-|2,239,525,614|-|-|6,735,612,586|105,432,448|6,630,180,138
Note|-|-|-|-|자사주소각|-|-|-|-|-
"""
# 5% holder reports by Samsung C&T: filing number, then MAJOR_KEYS values after the date.
MAJOR_TABLE = """
20260424000758|1,151,571,501|-8,476|19.70|-0.00|67,703,000|1.16
20260504000421|1,151,561,084|-10,417|19.70|-0.00|63,584,000|1.09
20260522000589|1,151,513,080|-48,004|19.70|-0.00|49,359,000|0.84
20260710000678|1,151,410,032|-103,048|19.69|-0.01|49,359,000|0.84
20260724000625|1,151,375,445|-34,587|19.69|-0.00|41,914,000|0.72
20260731000779|1,151,275,799|-99,646|19.69|-0.00|39,580,000|0.68
20260828001916|1,151,123,790|-152,009|19.69|-0.00|37,250,000|0.64
20261008000706|1,151,055,549|-68,241|19.69|-0.00|44,784,000|0.77
20261016000505|1,151,072,935|17,386|19.69|0.00|37,488,000|0.64
"""
# Insider reports: filing number, then INSIDER_KEYS values after the date.
INSIDER_TABLE = """
20251128000009|박승일|Unregistered executive|상무|10%이상주주|0|-5,000|0|0
20260721001074|김용관|Registered executive|사장|-|42,148|9,990|0.00|0.00
20260729000343|여명구|Registered executive|부사장|-|9,805|-500|0.00|0.00
20260917000097|신제윤|Registered executive|이사회의장, 독립이사|-|210|210|0.00|0.00
20260922000524|허은녕|Registered executive|독립이사|-|200|200|0.00|0.00
20261001000203|이석림|Unregistered executive|상무|-|2,344|-100|0.00|0.00
20261001000251|나현수|Unregistered executive|상무|-|1,351|-500|0.00|0.00
20261012000021|김은용|Unregistered executive|상무|-|179|-100|0.00|0.00
20261016000492|이재용|Unregistered executive|회장|Effective controlling shareholders|105,219,053|7,667,100|1.58|0.14
20261019000318|최고은|Unregistered executive|상무|-|1,115|80|0.00|0.00
"""
COUNTS = ("isu_stock_totqy", "now_to_isu_stock_totqy", "now_to_dcrs_stock_totqy", "redc")
COUNTS += ("profit_incnr", "rdmstk_repy", "etc", "istc_totqy", "tesstk_co", "distb_stock_co")
MAJOR_KEYS = ("stkqy", "stkqy_irds", "stkrt", "stkrt_irds", "ctr_stkqy", "ctr_stkrt")
INSIDER_KEYS = ("repror", "isu_exctv_rgist_at", "isu_exctv_ofcps", "isu_main_shrholdr")
INSIDER_KEYS += ("sp_stock_lmp_cnt", "sp_stock_lmp_irds_cnt", "sp_stock_lmp_rate")
INSIDER_KEYS += ("sp_stock_lmp_irds_rate",)
HOLDER_KEYS = ("stock_knd", "nm", "relate", "bsis_posesn_stock_co", "bsis_posesn_stock_qota_rt")
HOLDER_KEYS += ("trmend_posesn_stock_co", "trmend_posesn_stock_qota_rt", "rm")
CONTRACTS = "- 보유주식수 변동\n- 보유주식등에 관한 계약의 변경"


def table(text):
    return [line.replace("\\n", "\n").split("|") for line in text.strip().splitlines()]


def periodic(**fields):
    base = {"rcept_no": REPORT, "corp_cls": "Y", "corp_code": "00126380"}
    return {**base, "corp_name": "SAMSUNG ELECTRONICS", "stlm_dt": "2025-12-31", **fields}


def holder(cells):
    row = periodic(**dict(zip(HOLDER_KEYS, cells, strict=True)))
    return row if row["relate"] else {k: v for k, v in row.items() if k != "relate"}


def filed_report(number, keys, cells):
    filed = f"{number[:4]}-{number[4:6]}-{number[6:8]}"
    row = {"rcept_no": number, "rcept_dt": filed, "corp_code": "00126380", "corp_name": "삼성전자"}
    return row | dict(zip(keys, cells, strict=True))


HOLDERS = tuple(holder(cells) for cells in table(HOLDER_TABLE))
SHARES = tuple(
    periodic(se=se, **dict(zip(COUNTS, rest, strict=True))) for se, *rest in table(SHARE_TABLE)
)
MAJORS = tuple(
    filed_report(number, MAJOR_KEYS, rest)
    | {"repror": "삼성물산", "report_tp": "General", "report_resn": CONTRACTS}
    for number, *rest in table(MAJOR_TABLE)
)
INSIDERS = tuple(filed_report(number, INSIDER_KEYS, rest) for number, *rest in table(INSIDER_TABLE))
MINORITY = periodic(
    se="Minority shareholders",
    shrholdr_co="4,195,927",
    shrholdr_tot_co="4,196,025",
    shrholdr_rate="99.99%",
    hold_stock_co="3,909,148,867",
    stock_tot_co="5,919,637,922",
    hold_stock_rate="66.04%",
)
NO_CHANGES = periodic(
    change_on="-", mxmm_shrholdr_nm="-", posesn_stock_co="-", qota_rt="-", change_cause="-", rm="-"
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
    upstream.records("/hyslrSttus.json", *HOLDERS)
    upstream.records("/stockTotqySttus.json", *SHARES)
    upstream.records("/mrhlSttus.json", MINORITY)
    upstream.records("/hyslrChgSttus.json", NO_CHANGES)
    upstream.records("/majorstock.json", *MAJORS)
    upstream.records("/elestock.json", *INSIDERS)


async def call(client, **arguments):
    return await client.call_tool("get_ownership", arguments, raise_on_error=False)


@pytest.mark.anyio
async def test_tool_is_listed_with_its_schema_version_and_annotations(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    names = list(tools)
    assert names.index("get_ownership") < names.index("get_capital_structure")
    tool = tools["get_ownership"]
    assert tool.title == "Ownership and control"
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    schema = tool.input_schema
    assert schema["required"] == ["company"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "company",
        "activity_window",
        "period",
        "fiscal_year",
        "response_format",
    }
    assert schema["properties"]["activity_window"]["default"] == "180d"
    assert schema["properties"]["period"]["default"] == "latest"
    words = len(tool.description.split())
    assert 60 <= words <= 120
    assert "Args:" not in tool.description
    output = tool.output_schema["properties"]
    assert {"snapshot", "control_changes", "major_holder_reports", "insider_reports"} <= set(output)


@pytest.mark.anyio
async def test_snapshot_and_reports_from_the_latest_annual_report(client, upstream):
    samsung(upstream)
    result = await call(client, company="005930")
    assert not result.is_error
    data = result.structured_content
    assert (data["fiscal_year"], data["period"], data["period_end"]) == (2025, "FY", "2025-12-31")
    snapshot = data["snapshot"]
    assert snapshot["share_class"] == "common"
    assert snapshot["largest_shareholder"] == "삼성생명보험㈜"
    assert snapshot["controlling_pct"] == 19.84
    assert snapshot["controlling_pct_begin"] == 20.07
    assert snapshot["controlling_shares"] == 1_174_366_888
    assert snapshot["group_members"] == 19
    assert (snapshot["shares_issued"], snapshot["treasury_shares"]) == (5_919_637_922, 91_828_987)
    assert snapshot["shares_outstanding"] == 5_827_808_935
    assert snapshot["free_float_estimate_pct"] == 78.61
    group = snapshot["largest_shareholder_group"]
    assert len(group) == 10
    assert group[0] == {
        "name": "삼성생명보험㈜",
        "relation": "largest shareholder",
        "share_class": "common",
        "shares": 503_904_843,
        "pct_begin": 8.51,
        "pct_end": 8.51,
    }
    assert group[1]["name"] == "삼성물산㈜"
    assert group[1]["relation"] == "affiliate"
    assert {holder["share_class"] for holder in group} == {"common"}
    assert snapshot["minority"] == {
        "holders": 4_195_927,
        "total_holders": 4_196_025,
        "holder_pct": 99.99,
        "shares": 3_909_148_867,
        "share_pct": 66.04,
        "as_of": "2025-12-31",
    }
    assert data["control_changes"] == []
    assert data["source_filings"][0]["filing_number"] == REPORT
    assert data["source_filings"][0]["title"] == "Annual Report (2025.12)"
    assert any("free_float_estimate_pct is an estimate" in note for note in data["notes"])
    assert (
        "Showing the 10 largest common-share holdings of the group's 25; response_format='detailed' lists all of them."
        in data["notes"]
    )
    query = upstream.params("/hyslrSttus.json")[0]
    assert (query["corp_code"], query["bsns_year"], query["reprt_code"]) == (
        "00126380",
        "2025",
        "11011",
    )


@pytest.mark.anyio
async def test_holding_reports_are_filtered_to_the_window_newest_first(client, upstream):
    samsung(upstream)
    data = (await call(client, company="00126380")).structured_content
    assert (data["activity_since"], data["activity_until"]) == ("2026-04-25", "2026-10-22")
    majors = data["major_holder_reports"]
    assert [report["filed"] for report in majors][:2] == ["2026-10-16", "2026-10-08"]
    assert len(majors) == 8
    assert majors[0] == {
        "filed": "2026-10-16",
        "filing_number": "20261016000505",
        "reporter": "삼성물산",
        "report_type": "General",
        "shares": 1_151_072_935,
        "change_in_shares": 17_386,
        "pct": 19.69,
        "change_in_pct": 0.0,
        "reason": "보유주식수 변동; 보유주식등에 관한 계약의 변경",
    }
    assert majors[1]["change_in_pct"] == 0.0
    assert data["major_holder_activity"] == {
        "reports": 8,
        "shown": 8,
        "increases": 1,
        "decreases": 7,
        "net_change": -498_566,
    }
    insiders = data["insider_reports"]
    assert len(insiders) == 9
    assert insiders[0]["reporter"] == "최고은"
    chairman = insiders[1]
    assert chairman == {
        "filed": "2026-10-16",
        "filing_number": "20261016000492",
        "reporter": "이재용",
        "position": "회장",
        "is_registered_officer": False,
        "major_shareholder": "Effective controlling shareholders",
        "shares": 105_219_053,
        "change": 7_667_100,
        "pct": 1.58,
    }
    assert insiders[-1]["is_registered_officer"] is True
    assert data["insider_activity"] == {
        "reports": 9,
        "shown": 9,
        "increases": 5,
        "decreases": 4,
        "net_change": 7_676_380,
    }


@pytest.mark.anyio
async def test_text_view_has_summary_lines_and_tables(client, upstream):
    samsung(upstream)
    text = (await call(client, company="005930")).content[0].text
    assert text.startswith(
        "**SAMSUNG ELECTRONICS CO,.LTD (005930, KOSPI; DART 00126380): ownership and control (FY2025, period end 2025-12-31)**"
    )
    assert (
        "Largest shareholder: 삼성생명보험㈜. The group (19 holders) owns 1,174,366,888 common shares, 19.84% (20.07% at the period start)."
        in text
    )
    assert (
        "Common shares: 5,919,637,922 issued, 91,828,987 treasury, 5,827,808,935 outstanding"
        in text
    )
    assert "free float estimate 78.61%" in text
    assert "Minority shareholders as of 2025-12-31: 4,195,927 of 4,196,025 holders" in text
    assert "| Holder | Relation | Class | Shares | % start | % end |" in text
    assert "### 5% holder reports since 2026-04-25" in text
    assert "8 in the window (1 up, 7 down, net -498,566 shares); showing the newest 8." in text
    assert (
        "| 2026-10-16 | 이재용 | 회장 | no | Effective controlling shareholders | 105,219,053 | +7,667,100 | 1.58% | 20261016000492 |"
        in text
    )
    assert (
        "| Filed | Reporter | Position | Registered | Major holder | Shares | Change | % | Filing |"
        in text
    )
    assert "Changes of the largest shareholder" not in text
    assert "Sources: 20260310002820 (Annual Report (2025.12), 2026-03-10)." in text


@pytest.mark.anyio
async def test_detailed_lists_every_holding_and_field(client, upstream):
    samsung(upstream)
    result = await call(client, company="005930", response_format="detailed")
    data = result.structured_content
    group = data["snapshot"]["largest_shareholder_group"]
    assert len(group) == 25
    assert group[0]["shares_begin"] == 508_157_148
    assert group[0]["note"] == "시간외매매"
    assert group[-1]["share_class"] == "preferred"
    assert data["snapshot"]["minority"]["total_shares"] == 5_919_637_922
    assert data["major_holder_reports"][0]["contract_shares"] == 37_488_000
    assert data["insider_reports"][1]["change_pct"] == 0.14
    assert not any(note.startswith("Showing the") for note in data["notes"])
    text = result.content[0].text
    assert (
        "| Holder | Relation | Class | Shares (start) | Shares | % start | % end | Note |" in text
    )
    assert "Contract shares" in text


@pytest.mark.anyio
async def test_a_narrow_window_keeps_only_recent_reports(client, upstream):
    samsung(upstream)
    data = (await call(client, company="005930", activity_window="2026-10-10")).structured_content
    assert [r["filing_number"] for r in data["major_holder_reports"]] == ["20261016000505"]
    assert [r["reporter"] for r in data["insider_reports"]] == ["최고은", "이재용", "김은용"]


@pytest.mark.anyio
async def test_no_data_is_an_empty_result_with_notes(client, upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    result = await call(client, company="005930")
    assert not result.is_error
    data = result.structured_content
    assert "snapshot" not in data
    assert "fiscal_year" not in data
    assert data["control_changes"] == data["major_holder_reports"] == data["insider_reports"] == []
    assert data["insider_activity"]["reports"] == 0
    assert any("periods were chosen by filing deadlines" in note for note in data["notes"])
    assert any(
        note.startswith("No periodic report for Q3 2026, H1 2026, Q1 2026")
        for note in data["notes"]
    )
    text = result.content[0].text
    assert "No 5% holder reports were filed in the window." in text
    assert "No insider reports were filed in the window." in text


@pytest.mark.anyio
async def test_ambiguous_names_return_candidates(client):
    result = await call(client, company="Samsung")
    assert result.is_error
    assert "Ambiguous company" in result.content[0].text


@pytest.mark.anyio
async def test_unknown_companies_point_to_find_company(client):
    result = await call(client, company="999999")
    assert result.is_error
    assert "find_company" in result.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("window", "message"),
    [
        ("soon", "activity_window: Invalid date 'soon'"),
        ("2027-01-01", "activity_window '2027-01-01' starts after today (2026-10-22)"),
    ],
)
async def test_unusable_windows_are_explained(client, upstream, window, message):
    result = await call(client, company="005930", activity_window=window)
    assert result.is_error
    assert message in result.content[0].text
    assert upstream.count() == upstream.count("/corpCode.xml")


@pytest.mark.anyio
async def test_periods_that_have_not_ended_are_rejected(client, upstream):
    samsung(upstream)
    result = await call(client, company="005930", period="FY", fiscal_year=2026)
    assert result.is_error
    assert "No FY 2026 period is available" in result.content[0].text


@pytest.mark.anyio
async def test_schema_rejects_unknown_arguments(client):
    result = await call(client, company="005930", period="Q2")
    assert result.is_error


@pytest.mark.anyio
async def test_quota_exhaustion_is_explained(client, upstream):
    samsung(upstream)
    upstream.route("/hyslrSttus.json", upstream.status("020"))
    result = await call(client, company="005930")
    assert result.is_error
    assert "Retry after 00:00 KST" in result.content[0].text


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    async with Client(create_server(mcp_settings, transport=upstream.transport)) as client:
        result = await call(client, company="00126380")
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text
    assert upstream.count() == 0


@pytest.mark.anyio
async def test_snapshots_without_minority_figures_skip_that_line(client, upstream):
    samsung(upstream)
    upstream.route("/mrhlSttus.json", upstream.status("013"))
    result = await call(client, company="005930")
    assert "minority" not in result.structured_content["snapshot"]
    assert "Minority shareholders" not in result.content[0].text
