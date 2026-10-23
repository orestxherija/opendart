"""Preliminary earnings from KRX fair disclosures in trillion and million won."""

from __future__ import annotations

from opendart_mcp.documents import extract_preliminary_earnings, parse_filing

LABELS = ("(26.3Q)", "(26.2Q)", "(25.3Q)")


def extract(zipper, page: str):
    return extract_preliminary_earnings(parse_filing("20261008800004", zipper({"x.xml": page})))


def test_trillion_won_guidance(zipper, prelim):
    result = extract(zipper, prelim["page"]("단위 : 조원, %", prelim["trillion"], labels=LABELS))
    assert result is not None
    assert (result.basis, result.unit_label, result.unit_multiplier, result.unit_raw) == (
        "consolidated",
        "KRW trillion",
        10**12,
        "단위 : 조원, %",
    )
    assert [(p.key, p.start, p.end, p.column_label) for p in result.periods] == [
        ("current_quarter", "2026-07-01", "2026-09-30", "(26.3Q)"),
        ("prior_quarter", "2026-04-01", "2026-06-30", "(26.2Q)"),
        ("year_ago_quarter", "2025-07-01", "2025-09-30", "(25.3Q)"),
        ("year_to_date", "2026-01-01", "2026-09-30", None),
        ("prior_year_to_date", "2025-01-01", "2025-09-30", None),
    ]
    revenue = result.rows[0]
    assert revenue.metric == "revenue"
    assert revenue.current_quarter.model_dump() == {"krw": 195_000_000_000_000, "raw": "195.00"}
    assert revenue.year_ago_quarter.krw == 86_060_000_000_000
    assert revenue.quarter_on_quarter.model_dump() == {
        "percent": 13.7,
        "raw": "13.70",
        "turnaround": None,
        "turnaround_raw": "-",
    }
    assert revenue.year_to_date.krw == 500_370_000_000_000
    assert revenue.prior_year_to_date.krw == 239_770_000_000_000
    assert revenue.year_to_date_change.percent == 108.69
    assert [row.metric for row in result.rows] == [
        "revenue",
        "operating_profit",
        "pretax_profit",
        "net_profit",
        "net_profit_attributable_to_owners",
    ]
    assert result.rows[2].current_quarter.model_dump() == {"krw": None, "raw": "-"}
    assert result.notes[-1] == "Only revenue and operating profit are reported in this release."
    assert result.company_name == "테스트전자"
    assert not result.is_amendment


def test_million_won_results_with_losses_and_turnarounds(zipper, prelim):
    result = extract(zipper, prelim["page"]("단위 : 백만원, %", prelim["million"], labels=LABELS))
    assert result is not None
    assert (result.unit_label, result.unit_multiplier) == ("KRW million", 10**6)
    rows = {row.metric: row for row in result.rows}
    operating = rows["operating_profit"]
    assert operating.current_quarter.krw == -120_000_000
    assert operating.year_ago_quarter.krw == -30_000_000
    assert operating.year_to_date.krw == -100_000_000
    assert (operating.quarter_on_quarter.turnaround, operating.year_on_year.turnaround) == (
        "turned_loss",
        "loss_continued",
    )
    assert operating.year_to_date_change.turnaround == "turned_loss"
    assert rows["pretax_profit"].quarter_on_quarter.percent == -50.0
    owners = rows["net_profit_attributable_to_owners"]
    assert owners.quarter_on_quarter.turnaround == "turned_profit"
    assert owners.year_on_year.turnaround == "profit_continued"
    assert owners.year_to_date_change.model_dump() == {
        "percent": 200.0,
        "raw": "200.00",
        "turnaround": "other",
        "turnaround_raw": "기타",
    }
    assert rows["revenue"].current_quarter.krw == 1_234_000_000
    assert len(result.notes) == 1


def test_corrected_disclosures_are_flagged(zipper, prelim):
    page = prelim["page"](
        "단위 : 조원, %", prelim["trillion"], labels=LABELS, prefix=prelim["correction"]
    )
    parsed = parse_filing("20261009800001", zipper({"x.xml": page}))
    result = extract_preliminary_earnings(parsed)
    assert result is not None
    assert result.is_amendment
    assert result.rows[0].current_quarter.krw == 195_000_000_000_000
    amendment = parsed.amendment
    assert amendment is not None
    assert (amendment.original_filed, amendment.reason, amendment.section_id) == (
        "2026-10-08",
        "단순 오기 정정",
        "body",
    )
    assert [(c.item, c.before, c.after, c.reason) for c in amendment.changes] == [
        ("1. 연결실적내용\n- 매출액(당해실적)", "194.00", "195.00", "단순 오기 정정")
    ]


def test_missing_units_and_separate_basis(zipper, prelim):
    page = prelim["page"]("-", prelim["million"], labels=LABELS).replace(
        "연결재무제표기준영업(잠정)실적(공정공시)", "영업(잠정)실적(공정공시)"
    )
    result = extract(zipper, page)
    assert result is not None
    assert result.basis == "separate"
    assert (result.unit_label, result.unit_multiplier, result.unit_raw) == (None, None, None)
    assert result.rows[0].current_quarter.model_dump() == {"krw": None, "raw": "1,234"}
    assert "No unit statement was found" in result.notes[1]


def test_invalid_numbers_stay_verbatim(zipper, prelim):
    values = {
        "매출액": ["N/A", "abc", "NaN", "-", "1e2", "x", "-", "—", "-", "-", "-", "+5", "", "-"]
    }
    result = extract(zipper, prelim["page"]("단위 : 억원", values, labels=LABELS))
    assert result is not None
    (revenue,) = result.rows
    assert (revenue.current_quarter.krw, revenue.prior_quarter.krw) == (None, None)
    assert revenue.quarter_on_quarter.percent is None
    assert revenue.year_ago_quarter.krw == 10_000_000_000
    assert revenue.prior_year_to_date.krw == 500_000_000
    assert result.unit_label == "KRW 100 million"


def test_other_documents_are_not_preliminary_earnings(zipper, prelim, krx_adhoc, periodic):
    assert extract(zipper, krx_adhoc) is None
    assert extract(zipper, periodic()) is None
    title = "회사/연결재무제표기준영업(잠정)실적(공정공시)/(2026.10.08)제목"
    assert extract(zipper, prelim["krx"](title, "<p>표 없음</p>")) is None
