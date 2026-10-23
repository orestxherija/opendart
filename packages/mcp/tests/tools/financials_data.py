"""Synthetic OpenDART financial-statement answers shaped like the live English API.

Shapes follow live samples: the summary returns consolidated and separate rows in one
answer with comma-grouped amounts; full statements arrive sorted by account ID with plain
digits; quarterly income rows carry three-month amounts, year-to-date amounts, and
``frmtrm_q_amount``; indicators come one category per call; multi-company rows carry
``corp_code`` although the guide omits it. Every number here is synthetic.
"""

from __future__ import annotations

from typing import Any

T = 10**12
SAMSUNG, HYNIX, KAKAO = "00126380", "00164779", "00258801"
ANNUAL, HALF = "20260310002820", "20260814003699"
STOCKS = {SAMSUNG: "005930", HYNIX: "000660", KAKAO: "035720"}

PROFILE = {
    "corp_name": "삼성전자",
    "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
    "stock_code": "005930",
    "corp_cls": "Y",
    "acc_mt": "12",
}


def filing(number: str, title: str) -> dict[str, Any]:
    return {
        "corp_cls": "Y",
        "corp_name": "SAMSUNG ELECTRONICS",
        "corp_code": SAMSUNG,
        "stock_code": "005930",
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": "삼성전자",
        "rcept_dt": number[:8],
        "rm": "",
    }


FILINGS = [
    filing(HALF, "Semi-Annual Report (2026.06)"),
    filing("20260515003117", "Quarterly Report (2026.03)"),
    filing(ANNUAL, "Annual Report (2025.12)"),
]


def grouped(value: int | None) -> str:
    return "" if value is None else f"{value:,}"


# Summary lines: statement, account, (current, prior, two years prior) in trillions of won.
SUMMARY = [
    ("BS", "Current assets", (250, 230, 200)),
    ("BS", "Non-current assets", (320, 290, 260)),
    ("BS", "Total assets", (570, 520, 460)),
    ("BS", "Current liabilities", (100, 90, 80)),
    ("BS", "Non-current liabilities", (25, 20, 15)),
    ("BS", "Total liabilities", (125, 110, 95)),
    ("BS", "Total equity", (445, 410, 365)),
    ("IS", "Sales", (330, 300, 260)),
    ("IS", "Operating income", (44, 33, 6)),
    ("IS", "Profit(loss) before income tax", (50, 38, 11)),
    ("IS", "Profit", (45, 34, 15)),
    ("IS", "Profit(loss)", (45, 34, 15)),
    ("IS", "Total comprehensive income(loss)", (51, 50, 19)),
]

# Half-year summary: (current 3M, current YTD, prior-year 3M, prior-year YTD); BS: (end, prior FY end).
HALF_SUMMARY = [
    ("BS", "Current assets", (380, None, 250, None)),
    ("BS", "Total assets", (760, None, 570, None)),
    ("BS", "Current liabilities", (135, None, 100, None)),
    ("BS", "Total liabilities", (180, None, 125, None)),
    ("BS", "Total equity", (580, None, 445, None)),
    ("IS", "Sales", (170, 300, 75, 150)),
    ("IS", "Operating income", (90, 145, 5, 11)),
    ("IS", "Profit", (72, 118, 5, 13)),
]


def summary_rows(
    *,
    corp: str = SAMSUNG,
    year: str = "2025",
    scopes: tuple[str, ...] = ("CFS", "OFS"),
    scale: int = 1,
) -> list[dict[str, Any]]:
    """Annual major accounts for one company, both bases unless told otherwise."""
    rows = []
    for scope in scopes:
        factor = scale if scope == "CFS" else scale * 0.7
        for order, (sj, name, amounts) in enumerate(SUMMARY, 1):
            values = [round(a * factor * T) for a in amounts]
            rows.append(
                {
                    "rcept_no": ANNUAL,
                    "bsns_year": year,
                    "corp_code": corp,
                    "stock_code": STOCKS.get(corp, ""),
                    "reprt_code": "11011",
                    "account_nm": name,
                    "fs_div": scope,
                    "fs_nm": "Consolidated financial statements",
                    "sj_div": sj,
                    "sj_nm": "x",
                    "thstrm_nm": "Term 57",
                    "thstrm_dt": "2025.12.31",
                    "thstrm_amount": grouped(values[0]),
                    "frmtrm_nm": "Term 56",
                    "frmtrm_amount": grouped(values[1]),
                    "bfefrmtrm_nm": "Term 55",
                    "bfefrmtrm_amount": grouped(values[2]),
                    "ord": str(order),
                    "currency": "KRW",
                }
            )
    return rows


def half_summary_rows(*, corp: str = SAMSUNG, scale: int = 1) -> list[dict[str, Any]]:
    """Half-year major accounts (consolidated and separate)."""
    rows = []
    for scope in ("CFS", "OFS"):
        for order, (sj, name, (cur, cum, prior, prior_cum)) in enumerate(HALF_SUMMARY, 1):
            row = {
                "rcept_no": HALF,
                "bsns_year": "2026",
                "corp_code": corp,
                "stock_code": STOCKS.get(corp, ""),
                "reprt_code": "11012",
                "account_nm": name,
                "fs_div": scope,
                "sj_div": sj,
                "thstrm_amount": grouped(cur * scale * T),
                "frmtrm_amount": grouped(prior * scale * T),
                "ord": str(order),
                "currency": "KRW",
            }
            if cum is not None:
                row |= {
                    "thstrm_add_amount": grouped(cum * scale * T),
                    "frmtrm_add_amount": grouped(prior_cum * scale * T),
                }
            rows.append(row)
    return rows


NOT_USED = "-Standard account code not used-"
# Full annual statement lines: statement, account ID, name, detail, amounts (trillions unless per share).
FULL = [
    ("BS", "ifrs-full_Assets", "Total assets", "-", (570, 520, 460)),
    ("BS", "ifrs-full_CurrentAssets", "Current assets", "-", (250, 230, 200)),
    ("BS", "dart_ShortTermOtherReceivablesNet", "Non-trade receivables", "-", (7, 9, 6)),
    ("BS", "ifrs-full_CashAndCashEquivalents", "Cash and cash equivalents", "-", (58, 54, 69)),
    ("BS", "ifrs-full_Equity", "Total equity", "-", (445, 410, 365)),
    ("BS", "ifrs-full_CurrentLiabilities", "Current liabilities", "-", (100, 90, 80)),
    ("BS", NOT_USED, "Short-term borrowings", "-", (17, 13, 7)),
    ("BS", "ifrs-full_Liabilities", "Total liabilities", "-", (125, 110, 95)),
    ("IS", "dart_OperatingIncomeLoss", "Operating profit", "-", (44, 33, 6)),
    ("IS", "dart_OtherGains", "Other non-operating income", "-", (2, 2, 1)),
    (
        "IS",
        "dart_TotalSellingGeneralAdministrativeExpenses",
        "Selling and administrative expenses",
        "-",
        (88, 82, 72),
    ),
    (
        "IS",
        "ifrs-full_BasicEarningsLossPerShare",
        "Basic earnings per share",
        "-",
        ("6600", "4950", "2130"),
    ),
    ("IS", "ifrs-full_CostOfSales", "Cost of sales", "-", (200, 187, 180)),
    ("IS", "ifrs-full_GrossProfit", "Gross profit", "-", (130, 113, 80)),
    ("IS", "ifrs-full_ProfitLoss", "Profit for the year", "-", (45, 34, 15)),
    ("IS", "ifrs-full_Revenue", "Revenue", "-", (330, 300, 260)),
    ("IS", NOT_USED, "Other", "-", (1, 1, 1)),
    ("IS", NOT_USED, "Other", "-", (3, 2, 1)),
    (
        "CIS",
        "ifrs-full_ComprehensiveIncome",
        "Total comprehensive income for the year",
        "-",
        (51, 50, 19),
    ),
    ("CIS", "ifrs-full_ProfitLoss", "Profit for the year", "-", (45, 34, 15)),
    (
        "CF",
        "dart_CashAndCashEquivalentsAtEndOfPeriodCf",
        "Cash and cash equivalents at end of period",
        "-",
        (58, 54, 69),
    ),
    (
        "CF",
        "ifrs-full_CashFlowsFromUsedInFinancingActivities",
        "Cash flows from (used in) financing activities",
        "-",
        (-13, -8, -9),
    ),
    (
        "CF",
        "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        "Cash flows from (used in) operating activities",
        "-",
        (85, 73, 44),
    ),
    (
        "SCE",
        "dart_EquityAtBeginningOfPeriod",
        "Equity at beginning of period",
        "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]|이익잉여금 [구성요소]",
        (370, 345, 330),
    ),
    (
        "SCE",
        "dart_EquityAtBeginningOfPeriod",
        "Equity at beginning of period",
        "연결재무제표 [member]",
        (410, 365, 350),
    ),
    (
        "SCE",
        "ifrs-full_DividendsPaid",
        "Dividends declared",
        "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]|이익잉여금 [구성요소]",
        (-10, -11, -10),
    ),
    (
        "SCE",
        "ifrs-full_DividendsPaid",
        "Dividends declared",
        "연결재무제표 [member]",
        (-10, -11, -10),
    ),
    (
        "SCE",
        "ifrs-full_Equity",
        "Total equity",
        "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]|이익잉여금 [구성요소]",
        (400, 370, 345),
    ),
    ("SCE", "ifrs-full_Equity", "Total equity", "연결재무제표 [member]", (445, 410, 365)),
    (
        "SCE",
        "ifrs-full_ProfitLoss",
        "Profit for the year",
        "자본 [구성요소]|비지배지분 [구성요소]",
        (1, 1, 1),
    ),
]


def _won(value: int | str) -> str:
    return value if isinstance(value, str) else str(value * T)


def full_rows(
    *, year: str = "2025", corp: str = SAMSUNG, currency: str = "KRW"
) -> list[dict[str, Any]]:
    """An annual full statement (all five statements)."""
    rows = []
    for order, (sj, account_id, name, detail, amounts) in enumerate(FULL, 1):
        cur, prior, before = (_won(a) for a in amounts)
        rows.append(
            {
                "rcept_no": ANNUAL,
                "reprt_code": "11011",
                "bsns_year": year,
                "corp_code": corp,
                "sj_div": sj,
                "sj_nm": "x",
                "account_id": account_id,
                "account_nm": name,
                "account_detail": detail,
                "thstrm_nm": "Term 57",
                "thstrm_amount": cur,
                "frmtrm_amount": prior,
                "bfefrmtrm_amount": before,
                "thstrm_add_amount": "" if sj == "IS" else None,
                "ord": str(order),
                "currency": currency,
            }
        )
    return [{k: v for k, v in row.items() if v is not None} for row in rows]


def half_full_rows() -> list[dict[str, Any]]:
    """A half-year consolidated statement: IS with 3M and YTD, BS with the prior year end, CF year to date."""
    base = {
        "rcept_no": HALF,
        "reprt_code": "11012",
        "bsns_year": "2026",
        "corp_code": SAMSUNG,
        "account_detail": "-",
        "currency": "KRW",
    }
    income = [
        ("ifrs-full_Revenue", "Revenue", (170, 300, 75, 150)),
        ("dart_OperatingIncomeLoss", "Operating profit", (90, 145, 5, 11)),
        ("ifrs-full_ProfitLoss", "Profit", (72, 118, 5, 13)),
    ]
    rows = [
        base
        | {
            "sj_div": "IS",
            "account_id": i,
            "account_nm": n,
            "thstrm_amount": str(a * T),
            "thstrm_add_amount": str(b * T),
            "frmtrm_q_amount": str(c * T),
            "frmtrm_add_amount": str(d * T),
        }
        for i, n, (a, b, c, d) in income
    ]
    balance = [
        ("ifrs-full_Assets", "Total assets", (760, 570)),
        ("ifrs-full_CurrentAssets", "Current assets", (380, 250)),
        ("ifrs-full_CurrentLiabilities", "Current liabilities", (135, 100)),
        ("ifrs-full_Liabilities", "Total liabilities", (180, 125)),
        ("ifrs-full_Equity", "Total equity", (580, 445)),
    ]
    rows += [
        base
        | {
            "sj_div": "BS",
            "account_id": i,
            "account_nm": n,
            "thstrm_amount": str(a * T),
            "frmtrm_amount": str(b * T),
        }
        for i, n, (a, b) in balance
    ]
    rows.append(
        base
        | {
            "sj_div": "CF",
            "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "account_nm": "Operating cash flow",
            "thstrm_amount": str(60 * T),
            "frmtrm_q_amount": str(30 * T),
        }
    )
    return rows


INDICATORS = {
    "M210000": [
        ("M211100", "Pre-tax return on going concern ", None),
        ("M211200", "Net return", "13.6"),
        ("M211300", "Total sales return", "39.4"),
        ("M211550", "Return on equity", "10.8"),
        ("M212000", "Total return on business asset", "8.1"),
        ("M212400", "Return on business capital ", "#########"),
    ],
    "M220000": [
        ("M221000", "Equity ratio", "78.1"),
        ("M221100", "Liability ratio", "28.1"),
        ("M221200", "Current ratio", "250.0"),
    ],
    "M230000": [
        ("M231000", "Sales growth rate (YoY)", "10.0"),
        ("M231400", "Operating income growth rate(YoY)", "33.3"),
        ("M231800", "Net profit growth rate(YoY)", "32.4"),
    ],
    "M240000": [
        ("M241000", "Total asset turnover", "60.5"),
        ("M451000", "Dividend payout ratio(%)", "22.0"),
    ],
}


def indicator_rows(
    category: str, *, year: str = "2025", corps: tuple[str, ...] = (SAMSUNG,), shift: float = 0.0
) -> list[dict[str, Any]]:
    """Indicators of one category for one or more companies."""
    rows = []
    for number, corp in enumerate(corps):
        for code, name, value in INDICATORS[category]:
            adjusted = (
                value
                if value is None or not value[0].isdigit()
                else f"{float(value) + shift + number:.1f}"
            )
            row = {
                "reprt_code": "11011",
                "bsns_year": year,
                "corp_code": corp,
                "stock_code": STOCKS.get(corp, ""),
                "stlm_dt": f"{year}-12-31",
                "idx_cl_code": category,
                "idx_cl_nm": "x",
                "idx_code": code,
                "idx_nm": name,
            }
            rows.append(row if adjusted is None else row | {"idx_val": adjusted})
    return rows


def investment_rows(count: int = 25) -> list[dict[str, Any]]:
    """Equity investments: count investees (book values 1..count trillion won) and a total row."""
    rows = [
        {
            "rcept_no": ANNUAL,
            "corp_cls": "Y",
            "corp_code": SAMSUNG,
            "corp_name": "SAMSUNG ELECTRONICS",
            "inv_prm": f"투자회사{n:02d}",
            "frst_acqs_de": "1995.06.29",
            "invstmnt_purps": "경영참여" if n % 2 else "단순투자",
            "frst_acqs_amount": "250,000,000",
            "bsis_blce_qy": "1,000",
            "bsis_blce_qota_rt": "50.0",
            "bsis_blce_acntbk_amount": grouped(n * T - 10**9),
            "incrs_dcrs_acqs_dsps_qy": "-",
            "incrs_dcrs_acqs_dsps_amount": "1,000,000,000",
            "incrs_dcrs_evl_lstmn": "-",
            "trmend_blce_qy": "1,000",
            "trmend_blce_qota_rt": "50.0",
            "trmend_blce_acntbk_amount": grouped(n * T),
            "recent_bsns_year_fnnr_sttus_tot_assets": grouped(3 * n * T),
            "recent_bsns_year_fnnr_sttus_thstrm_ntpf": grouped(n * 10**11),
            "stlm_dt": "2025-12-31",
        }
        for n in range(1, count + 1)
    ]
    total = sum(range(1, count + 1)) * T
    rows.append(
        rows[0]
        | {
            "inv_prm": "Total",
            "invstmnt_purps": "-",
            "frst_acqs_de": "-",
            "trmend_blce_qota_rt": "-",
            "trmend_blce_acntbk_amount": grouped(total),
            "bsis_blce_acntbk_amount": grouped(total - count * 10**9),
        }
    )
    rows.insert(3, rows[0] | {"inv_prm": "소계", "trmend_blce_acntbk_amount": grouped(999 * T)})
    return rows


def by_params(
    table: dict[tuple[str, ...], dict[str, Any]], *keys: str, fallback: dict[str, Any] | None = None
):
    """Route answers by query parameters; unknown combinations answer 013 (no data)."""

    def route(request):
        key = tuple(request.url.params.get(name, "") for name in keys)
        return table.get(key, fallback or {"status": "013", "message": "no data"})

    return route


def samsung(upstream) -> None:
    """Route Samsung's profile and periodic-report index."""
    upstream.route("/company.json", upstream.ok(**PROFILE))
    upstream.records("/list.json", *FILINGS)
