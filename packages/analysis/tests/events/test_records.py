"""Grouping upstream rows into one record per filing, and section matching.

Responses are decoded JSON bodies; MCP's suite checks that SDK response models give the same
records.
"""

from __future__ import annotations

from types import SimpleNamespace

from opendart_analysis.events import labeled_fields, records_from
from scripts.testing.events import REDEMPTION, convertible_bond, equity_registration


def response(*rows):
    return {"status": "000", "message": "ok", "list": list(rows)}


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
    assert records_from("convertible_bond", {"status": "000", "message": "ok"}) == []
    assert records_from("convertible_bond", {"list": None, "group": "text"}) == []
    assert records_from("convertible_bond", object()) == []


def test_containers_are_also_read_as_attributes():
    model = SimpleNamespace(list=[convertible_bond("20261021000315")])
    (record,) = records_from("convertible_bond", model)
    assert record.raw("bd_tm") == "3"
    row = {"rcept_no": "20261021000435", "slprc": "1"}
    group = SimpleNamespace(title="General matters", list=[row])
    (record,) = records_from("equity_offering_registration", SimpleNamespace(group=[group]))
    assert (record.rows[0].section, record.raw("slprc")) == ("General matters", "1")


def test_registration_sections_are_matched_by_title_or_fields():
    body = equity_registration()
    body["group"].append({"list": [{"rcept_no": "20261021000435", "se": "시설자금", "amt": "1"}]})
    (record,) = records_from("equity_offering_registration", {"status": "000", **body})
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
    model = {"status": "000", "message": "ok", **equity_registration()}
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
