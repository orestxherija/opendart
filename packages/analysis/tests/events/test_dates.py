"""Schedule dates: field coverage, ranges, section meanings, board dates, flags, calendar kinds."""

from __future__ import annotations

from datetime import date

import pytest

from opendart_analysis.catalog import EVENT_KINDS, EVENT_KIND_NAMES, service
from opendart_analysis.events import (
    ACTIONS,
    CALENDAR_KINDS,
    FLAG_FIELDS,
    EventRecord,
    Row,
    board_date,
    event_dates,
    event_flags,
)
from opendart_analysis.events.dates import BOARD_DATE_FIELDS, DATE_FIELDS, IGNORED_DATE_FIELDS
from tests.support.events import REDEMPTION

NUMBER = "20261021000092"


def record(kind, *rows):
    return EventRecord(kind, NUMBER, tuple(Row(section, values) for section, values in rows))


@pytest.mark.parametrize("kind", EVENT_KIND_NAMES)
def test_every_date_field_has_a_meaning(kind):
    known = set(DATE_FIELDS) | set(BOARD_DATE_FIELDS) | IGNORED_DATE_FIELDS
    assert [name for name, _ in EVENT_KINDS[kind].date_fields if name not in known] == []


def test_the_tables_name_real_fields_and_actions():
    fields = {f.name for spec in EVENT_KINDS.values() for f in service(spec.service).fields}
    assert set(DATE_FIELDS) <= fields
    assert set(FLAG_FIELDS) <= fields
    assert set(DATE_FIELDS.values()) <= set(ACTIONS)
    starts = {code.removesuffix("_start") for code in ACTIONS if code.endswith("_start")}
    ends = {code.removesuffix("_end") for code in ACTIONS if code.endswith("_end")}
    assert starts == ends


def test_calendar_kinds_exclude_reports_with_only_facts():
    assert set(EVENT_KINDS) - CALENDAR_KINDS == {
        "asset_deal_put_back_option",
        "creditor_workout_suspension",
        "default_or_bankruptcy",
        "dissolution_cause",
        "lawsuit",
        "rehabilitation_filing",
    }
    assert ACTIONS["lawsuit_filed"].calendar is False
    assert ACTIONS["record_date"].label == "Record date"


def test_capital_reduction_dates_are_deduplicated_and_ranges_split():
    values = {
        "cr_std": "2026.11.06",
        "crsc_trspprpd": "2026.11.05 ~ 2026.11.27",
        "crsc_trspprpd_bgd": "2026.11.05",
        "crsc_trspprpd_edd": "2026.11.27",
        "crsc_nstklstprd": "2026.11.30",
        "crsc_gmtsck_prd": "-",
        "bddd": "2026.10.21",
        "cr_mth": "주식 병합",
    }
    assert event_dates(record("capital_reduction", ("", values))) == (
        ("suspension_start", date(2026, 11, 5)),
        ("record_date", date(2026, 11, 6)),
        ("suspension_end", date(2026, 11, 27)),
        ("listing_date", date(2026, 11, 30)),
    )


def test_registration_sections_give_expd_its_meaning():
    general = {"sbd": "2026.12.14 ~ 2026.12.15", "expd": "2027.03.01 ~ 2027.09.01"}
    redemption = {"expd": "2027.01.05 ~ 2027.04.05"}
    found = event_dates(
        record(
            "equity_offering_registration",
            ("General matters", general),
            (REDEMPTION, redemption),
        )
    )
    assert found == (
        ("subscription_start", date(2026, 12, 14)),
        ("subscription_end", date(2026, 12, 15)),
        ("redemption_claim_start", date(2027, 1, 5)),
        ("exercise_start", date(2027, 3, 1)),
        ("redemption_claim_end", date(2027, 4, 5)),
        ("exercise_end", date(2027, 9, 1)),
    )


def test_a_range_in_a_single_date_field_keeps_its_start():
    found = event_dates(record("convertible_bond", ("", {"pymd": "2026.11.12 ~ 2026.11.13"})))
    assert found == (("payment_date", date(2026, 11, 12)),)


def test_board_date_prefers_bddd_and_falls_back():
    assert board_date(record("merger", ("", {"bddd": "2026.10.19"}))) == date(2026, 10, 19)
    buyback = record("treasury_stock_acquisition", ("", {"aq_dd": "2026.10.19", "bddd": "-"}))
    assert board_date(buyback) == date(2026, 10, 19)
    assert board_date(record("lawsuit", ("", {"lgd": "2026.10.01"}))) is None


def test_flags_from_yes_no_columns_and_free_text():
    values = {
        "bdlst_atn": "Y",
        "otcpr_bdlst_sf_atn": "Non-applicable",
        "popt_ctr_atn": "Yes",
        "ftc_stt_atn": "Applicable",
        "n6m_tpai_plann": "-",
    }
    assert event_flags(record("business_acquisition", ("", values))) == (
        "backdoor_listing",
        "put_option",
        "ftc_reporting",
    )
    bond = record("convertible_bond", ("", {"bdis_mthn": "사모"}))
    assert event_flags(bond) == ("private_placement",)
    issue = record("combined_paid_and_bonus_issue", ("", {"piic_ic_mthn": "제3자배정"}))
    assert event_flags(issue) == ("third_party_allotment",)
    assert event_flags(record("rights_or_third_party_issue", ("", {"ic_mthn": "주주배정"}))) == ()


def test_a_trust_termination_restates_the_contract_period_as_facts():
    termination = {
        "ctr_pd_bfcc_bgd": "2026.06.01",
        "ctr_pd_bfcc_edd": "2026.12.01",
        "cc_prd": "2026.11.02",
        "bddd": "2026.10.20",
    }
    found = event_dates(record("treasury_trust_termination", ("", termination)))
    assert found == (
        ("terminated_trust_start", date(2026, 6, 1)),
        ("termination_date", date(2026, 11, 2)),
        ("terminated_trust_end", date(2026, 12, 1)),
    )
    assert [code for code, _ in found if ACTIONS[code].calendar] == ["termination_date"]
    assert "treasury_trust_termination" in CALENDAR_KINDS
    contract = {"ctr_pd_bgd": "2026.06.01", "ctr_pd_edd": "2026.12.01", "ctr_cns_prd": "2026.05.29"}
    assert event_dates(record("treasury_trust_contract", ("", contract))) == (
        ("contract_date", date(2026, 5, 29)),
        ("trust_start", date(2026, 6, 1)),
        ("trust_end", date(2026, 12, 1)),
    )


def test_a_range_ending_without_a_year_runs_into_the_next_year():
    general = ("General matters", {"sbd": "2026.12.28 ~ 01.08"})
    assert event_dates(record("equity_offering_registration", general)) == (
        ("subscription_start", date(2026, 12, 28)),
        ("subscription_end", date(2027, 1, 8)),
    )
