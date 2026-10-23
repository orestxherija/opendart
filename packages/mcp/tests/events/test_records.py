"""Grouping upstream rows into one record per filing, and section matching."""

from __future__ import annotations

from opendart.models.major_issues import CvbdIsDecsnResponse
from opendart.models.securities_registration import EstkRsResponse
from opendart_mcp.events import labeled_fields, records_from
from packages.mcp.tests.events.data import REDEMPTION, convertible_bond, equity_registration


def response(*rows):
    return CvbdIsDecsnResponse.model_validate(
        {"status": "000", "message": "ok", "list": list(rows)}
    )


def test_list_rows_become_one_record_per_filing():
    records = records_from(
        "convertible_bond",
        response(
            convertible_bond("20261021000315"),
            convertible_bond("20261021000302", bd_tm="4"),
            convertible_bond(""),
            convertible_bond("2026102100030"),
        ),
    )
    assert [r.filing_number for r in records] == ["20261021000315", "20261021000302"]
    first, second = records
    assert first.service == "cvbd_is_decsn"
    assert (first.raw("bd_tm"), second.raw("bd_tm")) == ("3", "4")
    assert first.value("bd_fta") == 30_000_000_000
    assert first.value("cvisstk_tisstk_vs") == 0.01
    assert first.raw("atcsc_rmislmt") is None  # a dash is blank
    assert first.rows[0].section == ""


def test_undocumented_fields_keep_their_names():
    (record,) = records_from("convertible_bond", response(convertible_bond(new_field="7")))
    assert record.raw("new_field") == "7"
    assert record.raw("corporation_code") == "00126380"


def test_missing_containers_give_no_records():
    empty = CvbdIsDecsnResponse.model_validate({"status": "000", "message": "ok"})
    assert records_from("convertible_bond", empty) == []
    assert records_from("convertible_bond", object()) == []


def test_registration_sections_are_matched_by_title_or_fields():
    body = equity_registration()
    body["group"].append({"list": [{"rcept_no": "20261021000435", "se": "시설자금", "amt": "1"}]})
    model = EstkRsResponse.model_validate({"status": "000", "message": "ok", **body})
    (record,) = records_from("equity_offering_registration", model)
    sections = [row.section for row in record.rows]
    assert sections == [
        "General matters",
        "Securities class",
        "Underwriter information",
        "Purpose of use of funds",
        REDEMPTION,
        "Purpose of use of funds",
    ]
    assert record.raw("slprc") == "4,915"
    assert record.raw("expd") == "2027.01.05 ~ 2027.04.05"  # the general matters value is a dash


def test_labeled_fields_skip_blanks_and_identity_and_use_section_labels():
    model = EstkRsResponse.model_validate(
        {"status": "000", "message": "ok", **equity_registration()}
    )
    (record,) = records_from("equity_offering_registration", model)
    fields = labeled_fields(record)
    names = {(f.section, f.name) for f in fields}
    assert ("General matters", "corporation_name") not in names
    assert ("General matters", "exstk") not in names
    by_key = {(f.section, f.name): f for f in fields}
    redemption = by_key[(REDEMPTION, "expd")]
    assert redemption.label == "Exercise period"
    assert redemption.value == "2027-01-05/2027-04-05"
    assert by_key[("Securities class", "slta")].value == 29_490_000_000


def test_labeled_fields_label_unknown_fields_by_name():
    (record,) = records_from("convertible_bond", response(convertible_bond(new_field="7")))
    unknown = next(f for f in labeled_fields(record) if f.name == "new_field")
    assert (unknown.label, unknown.value, unknown.section) == ("new_field", "7", "")
