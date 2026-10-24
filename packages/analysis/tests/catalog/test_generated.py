"""The generated catalog matches the upstream catalog: counts, labels, kinds, and shapes."""

from __future__ import annotations

import pytest

from opendart_analysis.catalog import (
    FIELD_KINDS,
    SERVICES,
    SERVICE_NAMES,
    FieldSpec,
    ParamSpec,
    RecordSpec,
    ServiceSpec,
)

SPECS = tuple(SERVICES.values())


def to_spec(data: dict) -> ServiceSpec:
    """Rebuild a ServiceSpec from the generator's plain data."""

    def fields(items: tuple[dict, ...]) -> tuple[FieldSpec, ...]:
        return tuple(FieldSpec(**item) for item in items)

    records = tuple(
        RecordSpec(**{**record, "fields": fields(record["fields"])})
        for record in data.get("records", ())
    )
    return ServiceSpec(
        **{
            **data,
            "params": tuple(ParamSpec(**param) for param in data.get("params", ())),
            "records": records,
            "scalar_fields": fields(data.get("scalar_fields", ())),
        }
    )


def test_catalog_is_fresh(built):
    """The committed module holds exactly what the generator builds from the catalog."""
    assert [to_spec(data) for data in built] == list(SPECS)
    assert tuple(data["name"] for data in built) == SERVICE_NAMES


def test_rendered_module_compiles(generator, built):
    source = generator.render(built)
    assert source.startswith(generator.HEADER)
    compile(source, "_generated.py", "exec")


def test_counts_follow_the_catalog():
    assert len(SERVICES) == 85
    groups = [spec.group for spec in SPECS]
    assert {group: groups.count(group) for group in sorted(set(groups))} == {
        "DE001": 4,
        "DE002": 30,
        "DE003": 7,
        "DE004": 2,
        "DE005": 36,
        "DE006": 6,
    }
    assert len({spec.api_id for spec in SPECS}) == 85
    assert sum(len(spec.fields) + len(spec.scalar_fields) for spec in SPECS) == 1974


@pytest.mark.parametrize("spec", SPECS, ids=SERVICE_NAMES)
def test_labels_and_kinds_are_complete(spec):
    assert spec.title
    assert spec.guide_url.startswith("https://engopendart.fss.or.kr/guide/detail.do?")
    for field in (*spec.fields, *spec.scalar_fields):
        assert field.label.strip() == field.label
        assert field.label
        assert not field.label.startswith('"')
        assert field.kind in FIELD_KINDS
        assert field.wire not in {"status", "message", "page_no", "total_count"}
    for record in spec.records:
        names = [field.name for field in record.fields]
        assert len(names) == len(set(names))


def test_record_shapes():
    shapes = {
        (record.path, record.model is None, bool(record.section))
        for spec in SPECS
        for record in spec.records
    }
    assert shapes == {
        (("list",), False, False),
        (("list",), True, False),
        (("group",), False, False),
        (("group", "list"), False, False),
        (("group", "list"), False, True),
    }
    registration = [spec for spec in SPECS if spec.resource == "securities_registration"]
    assert all(record.section for spec in registration for record in spec.records)
    estk = SERVICES["estk_rs"]
    assert [record.section for record in estk.records] == [
        "General matters",
        "Securities class",
        "Underwriter information",
        "Purpose of use of funds",
        "Matters relating to the seller",
        "General subscriber\u2019s redemption claim",
    ]
    assert estk.records[0].model == "EstkRsResponseGroupItemVariant1ListItem"


def test_scalar_and_archive_services():
    company = SERVICES["company"]
    assert company.records == ()
    assert [field.wire for field in company.scalar_fields][:3] == [
        "corp_name",
        "corp_name_eng",
        "stock_name",
    ]
    assert {spec.name for spec in SPECS if spec.archive} == {
        "document",
        "corporation_codes",
        "fnltt_xbrl",
    }
    directory = SERVICES["corporation_codes"]
    assert [field.wire for field in directory.fields] == [
        "corp_code",
        "corp_name",
        "corp_eng_name",
        "stock_code",
        "modify_date",
    ]
    assert directory.params == ()
    v2 = SERVICES["indvdl_by_pay_v2"]
    assert [record.path for record in v2.records] == [("group",), ("group", "list")]
    assert [field.wire for field in v2.scalar_fields] == [
        "rcept_no",
        "corp_cls",
        "corp_code",
        "corp_name",
        "stlm_dt",
    ]


def test_multi_company_services_take_a_list_of_codes():
    for name in ("fnltt_multi_acnt", "fnltt_cmpny_indx"):
        (codes,) = [param for param in SERVICES[name].params if param.wire == "corp_code"]
        assert codes.name == "corporation_codes"
