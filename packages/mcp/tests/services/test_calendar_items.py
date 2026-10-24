"""Calendar items: registration statements merged into their decisions, maturities replaced."""

from __future__ import annotations

import datetime as dt

from opendart_analysis.catalog import EVENT_KINDS
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.domain.identifiers import dart_viewer_url
from opendart_mcp.events import EventRecord, Row
from opendart_mcp.models.calendar import CalendarItem
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.calendar_items import REGISTERED, event_items, merge_maturities
from opendart_mcp.services.companies import Company

COMPANY = Company(
    ref=CompanyRef(name="Example Co.", corp_code="00126380", stock_code="005930", market="KOSPI"),
    fye_month=12,
    profile=None,
)
SPAN = DateWindow(dt.date(2026, 10, 22), dt.date(2030, 1, 1))
DECISION = "20260901000456"
STATEMENT = "20261015000123"


def record(kind, number, section="", **values):
    return EventRecord(kind, number, (Row(section, {"filing_number": number, **values}),))


def merger(number=DECISION):
    return record(
        "merger",
        number,
        mgptncmp_cmpnm="삼성전자서비스씨에스",
        mgsc_shddstd="2026.11.03",
        mgsc_mgop_rcpd_bgd="2026.11.03",
        mgsc_mgdt="2026.12.22",
    )


def merger_statement(link=DECISION):
    return record(
        "merger_registration",
        STATEMENT,
        "General matters",
        stn="Merger",
        gmtsck_shddstd="2026.11.03",
        ap_gmtsck="2026.11.25",
        mgdt_etc="2026.12.22",
        rpt_rcpn=link,
    )


def convertible(number, series="4"):
    return record(
        "convertible_bond",
        number,
        bd_tm=series,
        bd_fta="10,000,000,000",
        cvrqpd_bgd="2027.11.12",
        cvrqpd_edd="2029.10.12",
        bd_mtd="2029.11.12",
    )


def debt_statement(link, number="20261101000999"):
    return record(
        "debt_offering_registration",
        number,
        "General matters",
        fta="10,000,000,000",
        rpd="2029.11.12",
        estk_expd="2027.11.12 ~ 2029.10.12",
        rpt_rcpn=link,
    )


def rows(items):
    return [
        (str(i.date), i.action, i.source_kind, i.details.get("registration_filing")) for i in items
    ]


def test_every_registration_kind_names_the_decisions_it_registers():
    statements = {
        k for k, spec in EVENT_KINDS.items() if spec.resource == "securities_registration"
    }
    assert set(REGISTERED) == statements
    assert all(kinds and kinds <= set(EVENT_KINDS) - statements for kinds in REGISTERED.values())


def test_a_statement_repeating_its_decision_is_merged_into_the_decision():
    items = event_items(COMPANY, [merger(), merger_statement()], SPAN)
    assert sorted(rows(items)) == [
        ("2026-11-03", "objection_start", "merger", None),
        ("2026-11-03", "record_date", "merger", STATEMENT),
        ("2026-11-25", "shareholder_meeting", "merger_registration", None),
        ("2026-12-22", "effective_date", "merger", STATEMENT),
    ]
    kept = next(i for i in items if i.action == "record_date")
    assert (kept.filing_number, kept.details["event"]) == (DECISION, "Merger")
    assert kept.details["counterparty"] == "삼성전자서비스씨에스"


def test_an_amended_decision_is_paired_by_the_kinds_the_statement_registers():
    amended = "20261001000777"
    items = event_items(COMPANY, [merger(amended), merger_statement(link=DECISION)], SPAN)
    effective = [i for i in items if i.action == "effective_date"]
    assert [(i.filing_number, i.details["registration_filing"]) for i in effective] == [
        (amended, STATEMENT)
    ]


def test_statements_without_a_decision_link_are_never_merged():
    straight = debt_statement(link="-")
    items = event_items(COMPANY, [convertible("20261021000302"), straight], SPAN)
    maturities = [i for i in items if i.action == "maturity"]
    assert sorted(i.source_kind for i in maturities) == [
        "convertible_bond",
        "debt_offering_registration",
    ]
    assert all("registration_filing" not in i.details for i in items)


def test_a_debt_offering_exercise_window_matches_a_conversion_window():
    bond = convertible("20261021000302")
    items = event_items(COMPANY, [bond, debt_statement(link="20261021000302")], SPAN)
    assert sorted(rows(items)) == [
        ("2027-11-12", "conversion_start", "convertible_bond", "20261101000999"),
        ("2029-10-12", "conversion_end", "convertible_bond", "20261101000999"),
        ("2029-11-12", "maturity", "convertible_bond", "20261101000999"),
    ]


def test_two_deals_on_the_same_dates_stay_separate_and_an_exact_link_picks_one():
    series_4, series_5 = convertible("20261021000302"), convertible("20261021000315", "5")
    alone = event_items(COMPANY, [series_4, series_5], SPAN)
    assert [i.filing_number for i in alone if i.action == "conversion_start"] == [
        "20261021000302",
        "20261021000315",
    ]
    linked = event_items(COMPANY, [series_4, series_5, debt_statement("20261021000315")], SPAN)
    starts = [i for i in linked if i.action == "conversion_start"]
    assert [(i.filing_number, i.details.get("registration_filing")) for i in starts] == [
        ("20261021000302", None),
        ("20261021000315", "20261101000999"),
    ]


def test_an_ambiguous_statement_is_dropped_without_citing_either_decision():
    series_4, series_5 = convertible("20261021000302"), convertible("20261021000315", "5")
    items = event_items(COMPANY, [series_4, series_5, debt_statement("20250101000001")], SPAN)
    assert {i.source_kind for i in items} == {"convertible_bond"}
    assert len(items) == 6
    assert all("registration_filing" not in i.details for i in items)


def debt_item(day, face_value, number="20260325001401"):
    return CalendarItem(
        date=day,
        company=COMPANY.ref,
        action="debt_maturity",
        source_kind="debt_securities",
        filing_number=number,
        dart_url=dart_viewer_url(number),
        details={"event": "Debt maturity", "face_value": face_value, "redeemed": "no"},
    )


def test_a_debt_maturity_replaces_the_same_bonds_event_maturity():
    straight = event_items(COMPANY, [debt_statement(link="-")], SPAN)
    merged = merge_maturities(straight, [debt_item(dt.date(2029, 11, 12), 10_000_000_000)])
    assert [(i.action, i.source_kind) for i in merged] == [
        ("exercise_start", "debt_offering_registration"),
        ("exercise_end", "debt_offering_registration"),
        ("debt_maturity", "debt_securities"),
    ]
    assert merged[-1].details["offering_filing"] == "20261101000999"


def test_other_bonds_on_the_same_day_are_kept():
    straight = event_items(COMPANY, [debt_statement(link="-")], SPAN)
    different = debt_item(dt.date(2029, 11, 12), 20_000_000_000)
    unknown = debt_item(dt.date(2029, 11, 12), None).model_copy(
        update={"details": {"event": "Debt maturity"}}
    )
    merged = merge_maturities(straight, [different, unknown])
    assert [i.action for i in merged].count("maturity") == 1
    assert all("offering_filing" not in i.details for i in merged)
