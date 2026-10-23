"""Generator rules: title segments, labels, field kinds, and response trees."""

from __future__ import annotations

import dataclasses
from collections import Counter

import pytest

from opendart_mcp.registry import SERVICES
from opendart_mcp.registry.specs import FieldSpec

NUMERIC = "9,999,999,999"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Total assets", ["Total assets"]),
        (
            "Counterparty(Financial status (KRW)(Total assets))",
            ["Total assets", "Financial status (KRW)", "Counterparty"],
        ),
        (
            "Details of acquisition(Ratio to total assets (%) (A/B))",
            ["Ratio to total assets (%) (A/B)", "Details of acquisition"],
        ),
        ("Offering (sales) price", ["sales", "Offering price"]),
        # Unbalanced parentheses in the catalog.
        (
            "Terms of conversion(Conversion price (KRW/share)",
            ["Conversion price (KRW/share)", "Terms of conversion"],
        ),
        ('Interest rate("', ["Interest rate"]),
        ("Total number of issued stocks(Ⅱ-Ⅲ)", ["Total number of issued stocks(Ⅱ-Ⅲ)"]),
    ],
)
def test_segments_run_from_most_specific(generator, title, expected):
    assert generator.segments(title) == expected


@pytest.mark.parametrize(
    ("wire", "title", "description", "kind"),
    [
        # Identifiers and upstream yes/no suffixes.
        ("rcept_no", "Filing No.", "Filing No. (14 digits)", "code"),
        ("corp_cls", "Corporation type", "Corporation type: Y (KOSPI)", "code"),
        ("bdlst_atn", "Whether deemed a backdoor listing", "", "flag"),
        ("wnexpl_at", "Whether to exchange in Korean Won", "", "flag"),
        ("x", "Subject to reporting to the Fair Trade Commission", "", "flag"),
        # Money: totals versus amounts per share.
        ("x", "Total face(or electronically registered) value of bonds(KRW)", NUMERIC, "amount"),
        ("x", "Details of acquisition(Buying price(KRW))", NUMERIC, "amount"),
        ("x", "Assets Transfer/Acquisition Price", NUMERIC, "amount"),
        ("x", "Remuneration", "Remuneration", "amount"),
        ("x", "Terms of conversion(Conversion price (KRW/share)", NUMERIC, "per_share"),
        ("x", "Par value per share (KRW)", NUMERIC, "per_share"),
        ("x", "Price of shares to be disposed of (KRW)(Common stock)", NUMERIC, "per_share"),
        ("x", "Offering (sales) price", NUMERIC, "per_share"),
        ("x", "Underwriting price", "Underwriting price", "per_share"),
        # Counts, including unit markers several levels up.
        ("x", "Number of shares held", NUMERIC, "count"),
        ("x", "Number of shares to be acquired (shrs.)(Common stock)", NUMERIC, "count"),
        ("x", "Attendance of Outside Directors (Present)", NUMERIC, "count"),
        ("x", "Attendance of independent(outside) directors (Present (No.))", "", "count"),
        ("x", "Audit contract details (Hours)", "", "count"),
        ("x", "Total number of shares issued to date", "", "count"),
        ("x", "Stock options(Exercisable shares)", NUMERIC, "count"),
        # Percentages and ratios.
        ("x", "Shareholding ratio", "0.00", "percent"),
        ("x", "Interest rate", "0.00", "percent"),
        ("x", "Issue yield", "Issue yield", "percent"),
        ("x", "Details of transfer(Ratio to total assets(%)(A/B))", "", "percent"),
        ("x", "Merger ratio", "Merger ratio", "ratio"),
        (
            "x",
            "Number of new stocks allocated per share (common stock (shrs.))",
            "9,999,999,999.9x (up to 20 decimal points)",
            "ratio",
        ),
        # Dates and periods.
        ("x", "Establishment date (YYYYMMDD)", "", "date"),
        ("x", "Settlement date", "YYYY.MM.DD", "date"),
        ("x", "Terms of conversion(Conversion request period(Start date))", "", "date"),
        ("x", "Date of birth", "YYYYMM", "date"),
        ("x", "Exercise period", "Exercise period", "period"),
        ("x", "Fiscal year", "2019", "period"),
        ("x", "Month of settlement (MM)", "", "period"),
        # The most specific segment decides; text signals beat weaker numeric hints.
        (
            "x",
            "Counterparty to merger(Whether external audit was conducted(Name of Company))",
            "",
            "text",
        ),
        ("x", "Details of warrants(Calculation of exercise price)", "", "text"),
        ("x", "Purpose of fund procurement (issuance of new shares)", "", "text"),
        ("x", "Matters relating to appraisal rights (procedure, method, period)", "", "text"),
        ("x", "Overseas issuance(Basic exchange rate, etc.)", "", "text"),
        ("x", "Gender", "Male, female", "text"),
        # A title without signals falls back to the description.
        ("x", "Capital reduction", "Ⅲ. Total number of shares decreased to date", "count"),
        ("x", "Total", NUMERIC, "amount"),
    ],
)
def test_kind_rules(generator, wire, title, description, kind):
    assert generator.infer_kind("AE99999", wire, title, description) == kind


@pytest.mark.parametrize(
    ("api_id", "wire", "kind"),
    [
        ("AE00006", "thstrm", "number"),
        ("AE00038", "idx_val", "number"),
        ("AE00033", "frmtrm_dt", "period"),
        ("AE00012", "sm", "count"),
        ("AE00019", "sm", "amount"),
        ("AE00001", "rm", "code"),
        ("AE00009", "rm", "text"),
    ],
)
def test_kind_overrides_by_wire_name_and_service(generator, api_id, wire, kind):
    assert generator.infer_kind(api_id, wire, "Total", NUMERIC if wire == "sm" else "") == kind


@pytest.mark.parametrize(
    ("api_id", "field", "expected"),
    [
        (
            "AE99999",
            {
                "name": "mgsc_trspprpd_bgd",
                "title": '"Merger schedule(Start date)"',
                "description": "",
            },
            ("Merger schedule(Start date)", "title"),
        ),
        (
            "AE00017",
            {"name": "etc", "title": "Other", "description": "Ⅲ. Total decreased (4. Other)"},
            ("Ⅲ. Total decreased (4. Other)", "description"),
        ),
        (
            "AE99999",
            {"name": "sm", "title": "Total", "description": NUMERIC},
            ("Total", "title"),
        ),
        (
            "AE99999",
            {"name": "etc", "title": "Other", "description": NUMERIC},
            ("Other", "title"),
        ),
        (
            "AE00064",
            {"name": "ctr_pd_edd", "title": "Contract period(Start date)", "description": ""},
            ("Contract period(End date)", "override"),
        ),
        ("AE99999", {"name": "x", "title": "", "description": ""}, ("x", "name")),
    ],
)
def test_labels(generator, api_id, field, expected):
    assert generator.label(api_id, field) == expected


def test_label_overrides_and_fallbacks_are_recorded():
    sources = Counter(
        field.label_source
        for spec in SERVICES.values()
        for field in (*spec.fields, *spec.scalar_fields)
    )
    assert sources == {"title": 1967, "override": 6, "description": 1}
    fixed = SERVICES["cvbd_is_decsn"].records[0].fields
    (yield_field,) = [field for field in fixed if field.wire == "bd_intr_sf"]
    assert yield_field.label == "Interest rate(Yield to maturity (%))"
    assert yield_field.description == 'Interest rate("'


def test_reviewed_kind_distribution():
    """Pin the reviewed outcome so rule changes are deliberate."""
    kinds = Counter(
        field.kind for spec in SERVICES.values() for field in (*spec.fields, *spec.scalar_fields)
    )
    assert kinds == {
        "text": 587,
        "code": 343,
        "date": 274,
        "amount": 271,
        "count": 222,
        "flag": 107,
        "percent": 68,
        "per_share": 44,
        "period": 42,
        "ratio": 11,
        "number": 5,
    }


def test_overrides_name_documented_fields(generator):
    wires = {
        (spec.api_id, field.wire)
        for spec in SERVICES.values()
        for field in (*spec.fields, *spec.scalar_fields)
    }
    for key in generator.KIND_OVERRIDES:
        assert key in wires if isinstance(key, tuple) else any(key == wire for _, wire in wires)
    assert set(generator.LABEL_OVERRIDES) <= wires


def test_tree_repairs_the_indicator_indentation(generator):
    service = {
        "id": "AE00038",
        "fields": [
            {"name": "result", "indent": 5, "container": True},
            {"name": "status", "indent": 20, "container": False},
            {"name": "list", "indent": 20, "container": True},
            {"name": "idx_val", "indent": 20, "container": False},
        ],
    }
    status, (container, children) = generator.tree(service)
    assert status["name"] == "status"
    assert container["name"] == "list"
    assert [child["name"] for child in children] == ["idx_val"]


def test_records_number_repeated_sections(generator):
    def leaf(name, title="", description=""):
        return {"name": name, "title": title, "description": description, "container": False}

    def section(title, field):
        group = {"name": "group", "container": True}
        return (
            group,
            [leaf("title", "Group name", title), ({"name": "list"}, [leaf(field, "Amount")])],
        )

    nodes = [leaf("status"), section("First", "amt"), section("Second", "cnt")]
    found = generator.records("AE99999", nodes, "XResponse")
    assert [(r["path"], r["model"], r["section"]) for r in found] == [
        (("group", "list"), "XResponseGroupItemVariant1ListItem", "First"),
        (("group", "list"), "XResponseGroupItemVariant2ListItem", "Second"),
    ]
    assert [r["fields"][0]["wire"] for r in found] == ["amt", "cnt"]


def test_field_specs_are_written_in_declaration_order(generator):
    assert tuple(field.name for field in dataclasses.fields(FieldSpec)) == generator.FIELD_ORDER


def test_a_field_spec_missing_a_middle_argument_is_refused(generator):
    with pytest.raises(ValueError, match="FIELD_ORDER"):
        generator.literal(
            {"name": "a", "wire": "a", "description": "d", "kind": "text"}, "FieldSpec"
        )
