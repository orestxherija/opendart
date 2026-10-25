"""Per-kind presentations: completeness against the registry, templates, and golden headlines."""

from __future__ import annotations

import string
from datetime import date

import pytest

from opendart_analysis.catalog import EVENT_KINDS, EVENT_KIND_NAMES, service
from opendart_analysis.events import PRESENTATIONS, EventRecord, Row, describe
from opendart_analysis.events.templates import (
    Lookup,
    Presentation,
    headline,
    key_terms,
    part,
    ratio,
    total,
)
from tests.support.events import buyback, convertible_bond, merger, rights_issue

SAMPLE = {
    "amount": "1,000,000,000",
    "per_share": "5,000",
    "count": "1,000",
    "percent": "1.5",
    "ratio": "1 : 0.5",
    "number": "3",
    "date": "2026.11.02",
    "period": "2026.11.02 ~ 2026.11.30",
    "code": "7",
    "flag": "Y",
    "text": "sample text",
}


def record(kind, values, number="20261021000092"):
    return EventRecord(kind, number, (Row("", values),))


def filled(kind):
    """A record whose every documented field holds a plausible value for its kind."""
    spec = service(EVENT_KINDS[kind].service)
    return EventRecord(
        kind,
        "20261021000092",
        tuple(Row(r.section, {f.name: SAMPLE[f.kind] for f in r.fields}) for r in spec.records),
    )


def test_every_kind_has_a_presentation_in_registry_order():
    assert tuple(PRESENTATIONS) == EVENT_KIND_NAMES


@pytest.mark.parametrize("kind", EVENT_KIND_NAMES)
def test_presentations_name_real_fields_and_unique_terms(kind):
    presentation = PRESENTATIONS[kind]
    fields = {f.name for f in service(EVENT_KINDS[kind].service).fields}
    assert presentation.fields() <= fields
    keys = [key for key, _ in presentation.terms]
    assert len(keys) == len(set(keys))
    assert not {item.key for item in presentation.derived} & fields
    for fragment in (presentation.lead, *presentation.parts):
        slots = [
            name for _, name, _, _ in string.Formatter().parse(fragment.text) if name is not None
        ]
        assert len(slots) == len(fragment.fields), fragment


@pytest.mark.parametrize("kind", EVENT_KIND_NAMES)
def test_every_kind_describes_a_filled_report(kind):
    report = filled(kind)
    presentation = PRESENTATIONS[kind]
    view = describe(report)
    assert view.label == presentation.label
    assert view.group == EVENT_KINDS[kind].group
    lead = Lookup(presentation, report).render(presentation.lead)
    assert lead is not None
    assert view.headline.startswith(lead)
    assert set(view.key_terms) <= {key for key, _ in PRESENTATIONS[kind].terms}
    assert all(day == date(2026, 11, 2) or day == date(2026, 11, 30) for _, day in view.dates)


def test_convertible_bond_headline_and_terms():
    view = describe(record("convertible_bond", convertible_bond()))
    assert view.headline == (
        "KRW 30.0bn convertible bond, series 3, Private placement, coupon 1.5%, YTM 3%,"
        + " conversion price KRW 52,300, 573,613 new shares, 0.01% of total shares,"
        + " convertible 2027-09-30 to 2029-08-30, refixing floor KRW 36,610"
    )
    assert view.key_terms == {
        "face_value": 30_000_000_000,
        "series": "3",
        "coupon_pct": 1.5,
        "ytm_pct": 3.0,
        "conversion_price": 52300,
        "conversion_shares": 573613,
        "dilution_pct": 0.01,
        "refixing_floor": 36610,
        "method": "Private placement",
    }
    assert view.board_date == date(2026, 9, 15)
    assert view.flags == ("private_placement",)


def test_merger_buyback_and_rights_issue_headlines():
    assert describe(record("merger", merger())).headline == (
        "Merger with 삼성전자서비스씨에스, Small-scale merger, ratio 1 : 0.25, 1,200,000 new shares"
    )
    assert describe(record("treasury_stock_acquisition", buyback())).headline == (
        "Buyback of 175,467 common shares, about KRW 17.0bn,"
        + " 유가증권시장을 통한 장내 매수, purpose: 주주가치 제고"
    )
    assert describe(record("rights_or_third_party_issue", rights_issue())).headline == (
        "Paid-in capital increase of 1,470,587 common shares, 16.25% of shares before,"
        + " raising KRW 10.0bn, Capital increase by third-party allotment"
    )


def test_the_label_leads_when_the_lead_fields_are_blank():
    view = describe(record("convertible_bond", {"bd_fta": "-", "bd_tm": "2"}))
    assert view.headline == "Convertible bond, series 2"
    assert describe(record("lawsuit", {})).headline == "Lawsuit"


def test_derived_values_need_their_inputs():
    presentation = Presentation(
        label="Test",
        lead=part("{}", "share"),
        terms=(("share", "share"), ("sum", "sum")),
        derived=(
            ratio("share", "nstk_ostk_cnt", "bfic_tisstk_ostk"),
            total("sum", "fdpp_op", "fdpp_etc"),
        ),
    )
    zero = record("rights_or_third_party_issue", {"nstk_ostk_cnt": "10", "bfic_tisstk_ostk": "0"})
    assert key_terms(presentation, zero) == {}
    assert headline(presentation, zero) == "Test"
    missing = record("rights_or_third_party_issue", {"nstk_ostk_cnt": "10", "fdpp_etc": "5"})
    assert key_terms(presentation, missing) == {"sum": 5}


def test_long_text_terms_are_shortened():
    long_reason = "가" * 300
    terms = describe(record("capital_reduction", {"cr_rs": long_reason})).key_terms
    assert len(terms["reason"]) == 160
    assert terms["reason"].endswith("...")
