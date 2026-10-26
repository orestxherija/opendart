"""Debt registration statements that offer several tranches: one record and event per tranche."""

from __future__ import annotations

from datetime import date

from opendart_analysis.events import describe, labeled_fields, records_from
from scripts.testing.events import debt_registration, identity

NUMBER = "20261020000111"


def response(*bodies):
    groups = [group for body in bodies for group in body["group"]]
    return {"status": "000", "message": "ok", "group": groups}


def offering(*bodies):
    return records_from("debt_offering_registration", response(*bodies))


def test_each_tranche_becomes_a_record_with_its_own_rows():
    first, second = offering(debt_registration())
    assert first.filing_number == second.filing_number == NUMBER
    assert (first.raw("tm"), first.raw("fta"), first.raw("rpd")) == (
        "301-1",
        "100,000,000,000",
        "2029.11.05",
    )
    assert (second.raw("tm"), second.raw("fta"), second.raw("rpd")) == (
        "301-2",
        "200,000,000,000",
        "2031.11.05",
    )
    assert [row.section for row in second.rows] == [
        "General matters",
        "Underwriter information",
        "Purpose of use of funds",
        "Matters relating to the seller",
    ]
    assert {row.values["tm"] for row in second.rows} == {"301-2"}


def test_each_tranche_is_described_with_its_own_terms_and_dates():
    views = [describe(record) for record in offering(debt_registration())]
    assert [view.headline for view in views] == [
        "Debt offering of KRW 100.0bn 무보증사채, series 301-1, coupon 3.1%, yield 3.1%,"
        + " rating AA-(한국기업평가), underwriter NH투자증권",
        "Debt offering of KRW 200.0bn 무보증사채, series 301-2, coupon 3.4%, yield 3.4%,"
        + " rating AA-(한국기업평가), underwriter NH투자증권",
    ]
    second = views[1]
    assert list(second.key_terms)[:3] == ["face_value", "series", "coupon_pct"]
    assert (second.key_terms["face_value"], second.key_terms["offer_amount"]) == (
        200_000_000_000,
        200_000_000_000,
    )
    assert second.dates == (
        ("subscription", date(2026, 11, 5)),
        ("payment_date", date(2026, 11, 5)),
        ("maturity", date(2031, 11, 5)),
    )
    assert ("maturity", date(2029, 11, 5)) in views[0].dates
    assert ("maturity", date(2031, 11, 5)) not in views[0].dates


def test_rows_naming_no_known_tranche_go_to_every_tranche():
    body = debt_registration()
    funds = body["group"][2]["list"]
    funds.append({"rcept_no": NUMBER, **identity(), "se": "All issuance costs", "amt": "1,000"})
    funds.append({"rcept_no": NUMBER, **identity(), "tm": "999", "se": "기타", "amt": "5"})
    first, second = offering(body)
    for record in (first, second):
        shared = [f.raw for f in labeled_fields(record) if f.name == "se"]
        assert shared[-2:] == ["All issuance costs", "기타"]
    assert len(first.rows) == len(second.rows) == 6


def test_ordinals_match_across_spacing_and_the_korean_wrapper():
    body = debt_registration()
    underwriters = body["group"][1]["list"]
    underwriters[0]["tm"] = "제301-1회"
    underwriters[1]["tm"] = " 제 301-2 회 "
    first, second = offering(body)
    assert [row.values["udtamt"] for row in first.rows if "udtamt" in row.values] == [
        "100,000,000,000"
    ]
    assert [row.values["udtamt"] for row in second.rows if "udtamt" in row.values] == [
        "200,000,000,000"
    ]


def test_single_tranche_filings_stay_one_record_each():
    # Live layout: two filings, one tranche each, every section carrying the series.
    april = debt_registration("20260422000604", (("63", "400,000,000,000", "-", "2029.04.27"),))
    july = debt_registration("20260724000457", (("64", "200,000,000,000", "-", "2029.07.30"),))
    records = offering(april, july)
    assert [(r.filing_number, len(r.rows)) for r in records] == [
        ("20260422000604", 4),
        ("20260724000457", 4),
    ]
    headline = describe(records[0]).headline
    assert headline == (
        "Debt offering of KRW 400.0bn 무보증사채, series 63, rating AA-(한국기업평가),"
        + " underwriter NH투자증권"
    )


def test_a_filing_whose_tranches_share_one_ordinal_stays_whole():
    body = debt_registration(
        tranches=(("301", "1", "3", "2029.11.05"), ("301", "2", "3", "2031.11.05"))
    )
    (record,) = offering(body)
    assert len(record.rows) == 8


def test_reports_without_sections_are_never_split():
    rows = [
        {"rcept_no": NUMBER, **identity(), "tm": "3", "bdknd": "전환사채"},
        {"rcept_no": NUMBER, **identity(), "tm": "4", "bdknd": "전환사채"},
    ]
    model = {"status": "000", "message": "ok", "list": rows}
    (record,) = records_from("acquire_equity_linked_bonds", model)
    assert len(record.rows) == 2
