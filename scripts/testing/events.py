"""Synthetic event report bodies in OpenDART's wire format, shaped like live responses.

Values are invented; identifiers are the public ones of the sample directory. Shapes follow
live answers: amounts with separators, dashes for blanks, dates as YYYY.MM.DD (ranges with
"~" in registration statements), English yes/no words, and Korean free text.
"""

from __future__ import annotations

from typing import Any

from opendart_analysis.catalog import service

# The catalog title has a typographic apostrophe, as upstream sends it.
REDEMPTION = next(r.section for r in service("estk_rs").records if "redemption" in r.section)
SAMSUNG = ("00126380", "SAMSUNG ELECTRONICS CO,.LTD", "005930", "Y")
HYNIX = ("00164779", "SK hynix Inc.", "000660", "Y")


def identity(company: tuple[str, str, str, str] = SAMSUNG) -> dict[str, str]:
    """Return the identity columns every event row carries."""
    corp_code, name, _, corp_cls = company
    return {"corp_cls": corp_cls, "corp_code": corp_code, "corp_name": name}


def filing(number: str, title: str, company: tuple[str, str, str, str] = SAMSUNG) -> dict[str, str]:
    """Return one filing-search record."""
    corp_code, name, stock, corp_cls = company
    return {
        "corp_cls": corp_cls,
        "corp_name": name,
        "corp_code": corp_code,
        "stock_code": stock,
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": name,
        "rcept_dt": number[:8],
        "rm": "",
    }


def profile(company: tuple[str, str, str, str] = SAMSUNG) -> dict[str, str]:
    """Return a company overview body without status fields."""
    corp_code, name, stock, corp_cls = company
    return {
        "corp_code": corp_code,
        "corp_name": name,
        "corp_name_eng": name,
        "stock_code": stock,
        "corp_cls": corp_cls,
        "acc_mt": "12",
    }


def convertible_bond(
    number: str = "20260915000123",
    company: tuple[str, str, str, str] = SAMSUNG,
    **overrides: str,
) -> dict[str, Any]:
    """Return a convertible bond decision row."""
    row = {
        "rcept_no": number,
        **identity(company),
        "bd_tm": "3",
        "bd_knd": "무기명식 이권부 무보증 사모 전환사채",
        "bd_fta": "30,000,000,000",
        "atcsc_rmislmt": "-",
        "ovis_fta": "-",
        "fdpp_fclt": "-",
        "fdpp_op": "30,000,000,000",
        "bd_intr_ex": "1.5",
        "bd_intr_sf": "3.0",
        "bd_mtd": "2029.09.30",
        "bdis_mthn": "Private placement",
        "cv_rt": "100",
        "cv_prc": "52,300",
        "cvisstk_knd": "보통주",
        "cvisstk_cnt": "573,613",
        "cvisstk_tisstk_vs": "0.01",
        "cvrqpd_bgd": "2027.09.30",
        "cvrqpd_edd": "2029.08.30",
        "act_mktprcfl_cvprc_lwtrsprc": "36,610",
        "sbd": "2026.11.12",
        "pymd": "2026.11.12",
        "bddd": "2026.09.15",
        "od_a_at_t": "3",
        "od_a_at_b": "0",
        "adt_a_atn": "Absent",
        "rs_sm_atn": "No",
        "ex_sm_r": "사모 발행",
        "ftc_stt_atn": "Non-applicable",
    }
    return {**row, **overrides}


def merger(number: str = "20260901000456", **overrides: str) -> dict[str, Any]:
    """Return a merger decision row with a full schedule."""
    row = {
        "rcept_no": number,
        **identity(),
        "mg_mth": "흡수합병",
        "mg_stn": "Small-scale merger",
        "mg_pp": "경영 효율화",
        "mg_rt": "1 : 0.25",
        "exevl_atn": "Non-applicable",
        "exevl_pd": "-",
        "mgnstk_ostk_cnt": "1,200,000",
        "mgptncmp_cmpnm": "삼성전자서비스씨에스",
        "mgptncmp_rl_cmpn": "Subsidiary company",
        "mgsc_mgctrd": "2026.09.01",
        "mgsc_shddstd": "2026.11.03",
        "mgsc_mgop_rcpd_bgd": "2026.11.03",
        "mgsc_mgop_rcpd_edd": "2026.11.17",
        "mgsc_gmtsck_prd": "-",
        "mgsc_cdobprpd_bgd": "2026.11.20",
        "mgsc_cdobprpd_edd": "2026.12.21",
        "mgsc_mgdt": "2026.12.22",
        "mgsc_nstklstprd": "2027.01.08",
        "ffdtl_std": "2026.06.30",
        "bdlst_atn": "N/A",
        "popt_ctr_atn": "Yes",
        "popt_ctr_cn": "풋옵션 약정",
        "bddd": "2026.09.01",
    }
    return {**row, **overrides}


def buyback(
    number: str = "20261019000305", company: tuple[str, str, str, str] = HYNIX, **overrides: str
) -> dict[str, Any]:
    """Return a treasury stock acquisition decision row."""
    row = {
        "rcept_no": number,
        **identity(company),
        "aqpln_stk_ostk": "175,467",
        "aqpln_stk_estk": "-",
        "aqpln_prc_ostk": "17,002,800,000",
        "aqpln_prc_estk": "-",
        "aqexpd_bgd": "2026.10.20",
        "aqexpd_edd": "2027.01.20",
        "hdexpd_bgd": "-",
        "hdexpd_edd": "-",
        "aq_pp": "주주가치 제고",
        "aq_mth": "유가증권시장을 통한 장내 매수",
        "cs_iv_bk": "삼성증권",
        "aq_dd": "2026.10.19",
        "d1_prodlm_ostk": "101,168",
    }
    return {**row, **overrides}


def rights_issue(number: str = "20260801000777", **overrides: str) -> dict[str, Any]:
    """Return a paid-in capital increase decision row."""
    row = {
        "rcept_no": number,
        **identity(),
        "nstk_ostk_cnt": "1,470,587",
        "nstk_estk_cnt": "-",
        "fv_ps": "100",
        "bfic_tisstk_ostk": "9,048,223",
        "fdpp_op": "8,999,992,440",
        "fdpp_dtrp": "1,000,000,000",
        "ic_mthn": "Capital increase by third-party allotment",
        "ssl_at": "N",
        "ssl_bgd": "-",
        "ssl_edd": "-",
    }
    return {**row, **overrides}


def equity_registration(number: str = "20261021000435") -> dict[str, Any]:
    """Return an equity registration statement body with its sections."""
    ident = {"rcept_no": number, **identity()}
    general = {
        **ident,
        "sbd": "2026.12.14 ~ 2026.12.15",
        "pymd": "2026.12.22",
        "sband": "2026.12.16",
        "asand": "2026.12.21",
        "asstd": "2026.11.09",
        "exstk": "-",
        "exprc": "-",
        "expd": "-",
        "rpt_rcpn": "20260907000195",
    }
    securities = {
        **ident,
        "stksen": "Common stock",
        "stkcnt": "6,000,000",
        "fv": "500",
        "slprc": "4,915",
        "slta": "29,490,000,000",
        "slmthn": "Shareholder allotment",
    }
    underwriters = {**ident, "actsen": "Lead", "actnmn": "SK Securities", "udtmth": "잔액인수"}
    funds = [{**ident, "se": "운영자금", "amt": "19,490,000,000"}]
    redemption = {**ident, "grtrs": "-", "expd": "2027.01.05 ~ 2027.04.05", "exprc": "4,424"}
    return {
        "group": [
            {"title": "General matters", "list": [general]},
            {"title": "Securities class", "list": [securities]},
            {"title": "Underwriter information", "list": [underwriters]},
            {"title": "Fund use purposes", "list": funds},
            {"title": REDEMPTION, "list": [redemption]},
        ]
    }


TRANCHES = (
    ("301-1", "100,000,000,000", "3.10", "2029.11.05"),
    ("301-2", "200,000,000,000", "3.40", "2031.11.05"),
)


def debt_registration(
    number: str = "20261020000111",
    tranches: tuple[tuple[str, str, str, str], ...] = TRANCHES,
) -> dict[str, Any]:
    """Return a debt registration body with series, face value, coupon, and maturity.

    Every section repeats the series (tm), as in live answers.
    """
    ident = {"rcept_no": number, **identity()}
    general = [
        {
            **ident,
            "tm": series,
            "bdnmn": "무보증사채",
            "slmth": "공모",
            "fta": face,
            "slta": face,
            "isprc": face,
            "intr": coupon,
            "isrr": coupon,
            "rpd": maturity,
            "cdrt_int": "AA-(한국기업평가)",
            "sbd": "2026.11.05",
            "pymd": "2026.11.05",
            "udtintnm": "NH투자증권",
            "drcb_at": "N",
        }
        for series, face, coupon, maturity in tranches
    ]
    lead = {"actsen": "Lead", "actnmn": "NH Investment and Securities", "udtmth": "총액인수"}
    underwriters = [{**ident, "tm": t[0], **lead, "udtamt": t[1]} for t in tranches]
    funds = [{**ident, "tm": t[0], "se": "채무상환자금", "amt": t[1]} for t in tranches]
    return {
        "group": [
            {"title": "General matters", "list": general},
            {"title": "Underwriter information", "list": underwriters},
            {"title": "Fund use purposes", "list": funds},
            {
                "title": "Matters relating to the seller",
                "list": [{**ident, "tm": t[0]} for t in tranches],
            },
        ]
    }
