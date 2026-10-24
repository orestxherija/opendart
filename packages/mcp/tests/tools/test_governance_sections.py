"""get_governance over the MCP protocol: executives, compensation, and employees."""

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
V2_DIRECTORS = "/hmvAuditIndvdlBySttusV2.json"
V1_DIRECTORS = "/hmvAuditIndvdlBySttus.json"
V2_TOP = "/indvdlByPayV2.json"
V1_TOP = "/indvdlByPay.json"


def samsung(upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    upstream.records(
        "/list.json",
        {
            "corp_cls": "Y",
            "corp_name": "SAMSUNG ELECTRONICS CO,.LTD",
            "corp_code": "00126380",
            "stock_code": "005930",
            "report_nm": "Annual Report (2025.12)",
            "rcept_no": ANNUAL,
            "flr_nm": "삼성전자",
            "rcept_dt": "20260310",
            "rm": "",
        },
    )


def executive(name, role, **fields):
    record = {
        "rcept_no": ANNUAL,
        "nm": name,
        "sexdstn": "Female",
        "birth_ym": "1967.06",
        "ofcps": "이사",
        "rgist_exctv_at": role,
        "fte_at": "Part-time",
        "chrg_job": "ㆍ감사위원회 위원ㆍ보상위원회\n   위원",
        "main_career": "ㆍ가나대 교수",
        "mxmm_shrholdr_relate": "계열회사 임원",
        "hffc_pd": "38개월",
        "tenure_end_on": "2028.03.18",
    }
    return record | fields


def pay_tables(upstream):
    upstream.records(
        "/drctrAdtAllMendngSttusGmtsckConfmAmount.json",
        {
            "rcept_no": ANNUAL,
            "se": "등기이사",
            "nmpr": "4",
            "gmtsck_confm_amount": "-",
            "fscl_year": "-",
        },
        {
            "rcept_no": ANNUAL,
            "se": "계",
            "nmpr": "10",
            "gmtsck_confm_amount": "36,000,000,000",
            "fscl_year": "-",
        },
    )
    upstream.records(
        "/hmvAuditAllSttus.json",
        {
            "rcept_no": ANNUAL,
            "nmpr": "9",
            "mendng_totamt": "28,052,000,000",
            "jan_avrg_mendng_am": "3,006,000,000",
            "fscl_year": "-",
        },
    )
    upstream.records(
        "/drctrAdtAllMendngSttusMendngPymntamtTyCl.json",
        {
            "rcept_no": ANNUAL,
            "se": "Outside director (excluding members of the audit committee)",
            "nmpr": "3",
            "pymnt_totamt": "678,000,000",
            "psn1_avrg_pymntamt": "220,000,000",
            "fscl_year": "-",
        },
        {
            "rcept_no": ANNUAL,
            "se": "Auditor",
            "nmpr": "-",
            "pymnt_totamt": "-",
            "psn1_avrg_pymntamt": "-",
            "fscl_year": "-",
        },
    )
    upstream.records(
        "/unrstExctvMendngSttus.json",
        {
            "rcept_no": ANNUAL,
            "se": "Unregistered executive",
            "nmpr": "989",
            "fyer_salary_totamt": "705,452,000,000",
            "jan_salary_am": "744,000,000",
            "rm": "-",
        },
    )
    upstream.records(
        V1_DIRECTORS,
        {
            "rcept_no": ANNUAL,
            "nm": "갑",
            "ofcps": "대표이사",
            "mendng_totamt": "5,606,000,000",
            "mendng_totamt_ct_incls_mendng": "RSA 5,135주 약정",
        },
    )
    upstream.records(
        V1_TOP,
        {
            "rcept_no": ANNUAL,
            "nm": "을",
            "ofcps": "부회장\n(前대표이사)",
            "mendng_totamt": "13,407,000,000",
            "mendng_totamt_ct_incls_mendng": "-",
        },
    )


@pytest.mark.anyio
async def test_executives_keep_registered_officers_in_concise_results(client, upstream):
    samsung(upstream)
    upstream.records(
        "/exctvSttus.json",
        executive(
            "갑", "Executive Directors", fte_at="Full-time", ofcps="부회장", chrg_job="ㆍ대표이사"
        ),
        executive("을", "Outside Director"),
        executive("병", "Unregistered executive"),
    )
    result = await client.call_tool(
        "get_governance", {"company": "005930", "sections": ["executives"]}
    )
    data = result.structured_content
    assert data["executives"] == [
        {
            "name": "갑",
            "position": "부회장",
            "role": "executive_director",
            "full_time": True,
            "responsibilities": "대표이사",
            "term_ends": "2028-03-18",
        },
        {
            "name": "을",
            "position": "이사",
            "role": "outside_director",
            "full_time": False,
            "responsibilities": "감사위원회 위원; 보상위원회 위원",
            "term_ends": "2028-03-18",
        },
    ]
    assert (
        "1 unregistered executives are omitted; response_format='detailed' lists them."
        in data["notes"]
    )
    assert (
        "| 을 | 이사 | outside_director | no | 감사위원회 위원; 보상위원회 위원 | 2028-03-18 |"
        in result.content[0].text
    )
    detailed = await client.call_tool(
        "get_governance",
        {"company": "005930", "sections": ["executives"], "response_format": "detailed"},
    )
    people = detailed.structured_content["executives"]
    assert [person["role"] for person in people] == [
        "executive_director",
        "outside_director",
        "unregistered",
    ]
    assert (people[1]["gender"], people[1]["born"], people[1]["tenure"]) == (
        "female",
        "1967-06",
        "38개월",
    )


@pytest.mark.anyio
async def test_concise_results_without_registered_officers_note_both(client, upstream):
    samsung(upstream)
    upstream.records("/exctvSttus.json", executive("병", "Unregistered executive"))
    result = await client.call_tool(
        "get_governance", {"company": "005930", "sections": ["executives", "board"]}
    )
    data = result.structured_content
    assert "executives" not in data
    assert data["notes"] == [
        "1 unregistered executives are omitted; response_format='detailed' lists them.",
        "No executives data in the FY2025 report.",
        "No board data in the FY2025 report.",
        "Flags come from the audit section, which was not requested.",
    ]


@pytest.mark.anyio
async def test_compensation_falls_back_to_version_one_services(client, upstream):
    samsung(upstream)
    pay_tables(upstream)
    result = await client.call_tool(
        "get_governance", {"company": "005930", "sections": ["compensation"]}
    )
    pay = result.structured_content["compensation"]
    assert (pay["approved_cap"], pay["paid_total"], pay["headcount"], pay["average"]) == (
        36_000_000_000,
        28_052_000_000,
        9,
        3_006_000_000,
    )
    assert pay["by_type"] == [
        {
            "category": "Outside director (excluding members of the audit committee)",
            "headcount": 3,
            "total": 678_000_000,
            "average": 220_000_000,
        }
    ]
    assert pay["directors_over_500m"] == [
        {"name": "갑", "position": "대표이사", "total": 5_606_000_000}
    ]
    assert pay["top_paid"] == [
        {"name": "을", "position": "부회장 (前대표이사)", "total": 13_407_000_000}
    ]
    assert pay["unregistered_executives"]["headcount"] == 989
    assert [upstream.count(path) for path in (V2_DIRECTORS, V1_DIRECTORS, V2_TOP, V1_TOP)] == [
        1,
        1,
        1,
        1,
    ]
    text = result.content[0].text
    assert (
        "Approved ceiling 36,000.0; paid 28,052.0 to 9 directors and auditors (average 3,006.0)."
        in text
    )
    assert "### Top paid (KRW 500 million or more)" in text


@pytest.mark.anyio
async def test_compensation_prefers_version_two_services(client, upstream):
    samsung(upstream)
    pay_tables(upstream)
    upstream.route(
        V2_DIRECTORS,
        upstream.ok(
            rcept_no=ANNUAL,
            group=[
                {
                    "nm": "정",
                    "fscl_year": "2025",
                    "ofcps": "사장",
                    "mendng_totamt": "2,000,000,000",
                    "list": [{"stk_bsd_pd_mendng_totamt_knd": "RSU", "stk_opt_rmn_blce": "-"}],
                },
                {
                    "nm": "정",
                    "fscl_year": "2024",
                    "ofcps": "사장",
                    "mendng_totamt": "1,500,000,000",
                    "list": [],
                },
            ],
        ),
    )
    upstream.route(V2_TOP, upstream.ok(rcept_no=ANNUAL, group=[]))
    result = await client.call_tool(
        "get_governance",
        {"company": "005930", "sections": ["compensation"], "response_format": "detailed"},
    )
    pay = result.structured_content["compensation"]
    assert pay["directors_over_500m"] == [
        {"name": "정", "position": "사장", "total": 2_000_000_000}
    ]
    assert pay["top_paid"][0]["name"] == "을"
    assert pay["directors_over_500m"][0].get("not_in_total") is None
    assert [upstream.count(path) for path in (V2_DIRECTORS, V1_DIRECTORS, V2_TOP, V1_TOP)] == [
        1,
        0,
        1,
        1,
    ]


@pytest.mark.anyio
async def test_employees_summarize_subtotal_rows(client, upstream):
    samsung(upstream)

    def staff(division, sex, total, **fields):
        record = {
            "rcept_no": ANNUAL,
            "fo_bbm": division,
            "sexdstn": sex,
            "rgllbr_co": "-",
            "cnttk_co": "-",
            "sm": total,
            "avrg_cnwk_sdytrn": "      12.0",
            "fyer_salary_totamt": "-",
            "jan_salary_am": "-",
            "rm": "-",
        }
        return record | fields

    upstream.records(
        "/empSttus.json",
        staff("DX", "Male", "300", rgllbr_co="290", cnttk_co="10"),
        staff("DX", "Female", "100", rgllbr_co="98", cnttk_co="2"),
        staff(
            "성별합계",
            "Male",
            "300",
            cnttk_co="10",
            fyer_salary_totamt="30,000,000,000",
            jan_salary_am="100,000,000",
        ),
        staff(
            "성별합계",
            "Female",
            "100",
            cnttk_co="2",
            fyer_salary_totamt="8,000,000,000",
            jan_salary_am="80,000,000",
        ),
    )
    result = await client.call_tool(
        "get_governance", {"company": "005930", "sections": ["employees"]}
    )
    staff_data = result.structured_content["employees"]
    assert (staff_data["total"], staff_data["fixed_term"], staff_data["average_salary"]) == (
        400,
        12,
        95_000_000,
    )
    assert staff_data["average_tenure_years"] == 12.0
    assert [group["gender"] for group in staff_data["groups"]] == ["male", "female"]
    text = result.content[0].text
    assert (
        "Employees 400 (fixed-term 12); total salary 38,000.0; average salary 95.0; average tenure 12.0 years."
        in text
    )
