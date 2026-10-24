"""The generated registry matches the catalog and the SDK's methods, parameters, and models."""

from __future__ import annotations

import importlib
import inspect
import types
import typing
from typing import Any

import pytest
from pydantic import BaseModel

from opendart import OpenDARTError
from opendart_mcp.registry import (
    FIELD_KINDS,
    RESOURCES,
    SERVICES,
    SERVICE_NAMES,
    FieldSpec,
    ParamSpec,
    RecordSpec,
    ServiceSpec,
    sdk_method,
)

SPECS = tuple(SERVICES.values())
# A valid value for every required upstream parameter.
VALID = {
    "corp_code": "00126380",
    "bgn_de": "20250101",
    "end_de": "20250131",
    "bsns_year": "2024",
    "reprt_code": "11011",
    "fs_div": "CFS",
    "idx_cl_code": "M210000",
    "sj_div": "BS1",
    "rcept_no": "20190401004781",
}


def resource_class(resource: str) -> type:
    module = importlib.import_module(f"opendart.resources.{resource}")
    (cls,) = [
        value
        for value in vars(module).values()
        if inspect.isclass(value) and value.__module__ == module.__name__
    ]
    return cls


def sdk_methods() -> set[tuple[str, str]]:
    return {
        (resource, name)
        for resource in RESOURCES
        for name, member in inspect.getmembers(resource_class(resource))
        if not name.startswith("_") and inspect.iscoroutinefunction(member)
    }


def method(spec: ServiceSpec) -> Any:
    return getattr(resource_class(spec.resource), spec.name)


def model_class(resource: str, name: str) -> type[BaseModel]:
    model = getattr(importlib.import_module(f"opendart.models.{resource}"), name)
    assert issubclass(model, BaseModel)
    return model


def models_in(annotation: Any) -> set[type]:
    """Collect model classes from an annotation such as list[A | B] | None."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation}
    return {model for arg in typing.get_args(annotation) for model in models_in(arg)}


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


def test_registry_is_fresh(built):
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


def test_every_sdk_method_appears_exactly_once():
    registered = [(spec.resource, spec.name) for spec in SPECS]
    assert len(registered) == len(set(registered))
    assert set(registered) == sdk_methods()
    assert list(SERVICES) == [spec.name for spec in SPECS]


@pytest.mark.parametrize("spec", SPECS, ids=SERVICE_NAMES)
def test_params_match_the_sdk_signature(spec):
    signature = inspect.signature(method(spec))
    keywords = {
        name: parameter
        for name, parameter in signature.parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    assert [param.name for param in spec.params] == list(keywords)
    for param in spec.params:
        assert param.required is (keywords[param.name].default is inspect.Parameter.empty)
        assert param.title
        assert param.wire != "crtfc_key"


@pytest.mark.parametrize("spec", SPECS, ids=SERVICE_NAMES)
def test_archives_return_bytes(spec):
    returns = typing.get_type_hints(method(spec))["return"]
    if spec.archive:
        assert returns is bytes
        assert spec.path.endswith(".xml")
    else:
        assert issubclass(returns, BaseModel)
        assert spec.path.endswith(".json")


@pytest.mark.anyio
@pytest.mark.parametrize("spec", SPECS, ids=SERVICE_NAMES)
async def test_calls_reach_the_registered_path_with_wire_names(spec, sdk, upstream):
    arguments = {
        param.name: [VALID[param.wire]] if param.name == "corporation_codes" else VALID[param.wire]
        for param in spec.params
        if param.required
    }
    with pytest.raises(OpenDARTError):  # The fake upstream answers 013 (no data).
        await sdk_method(sdk, spec)(**arguments)
    assert upstream.count(spec.path) == 1
    assert upstream.params(spec.path) == [
        {param.wire: VALID[param.wire] for param in spec.params if param.required}
    ]


@pytest.mark.parametrize("spec", SPECS, ids=SERVICE_NAMES)
def test_fields_exist_on_the_sdk_models(spec):
    response = typing.get_type_hints(method(spec))["return"]
    for record in spec.records:
        if record.model is None:
            assert spec.archive
            continue
        model = model_class(spec.resource, record.model)
        reachable = {response}
        for attribute in record.path:
            reachable = {
                found
                for parent in reachable
                if attribute in parent.model_fields
                for found in models_in(parent.model_fields[attribute].annotation)
            }
        assert model in reachable
        for field in record.fields:
            assert field.name in model.model_fields, (record.model, field.name)
            assert (model.model_fields[field.name].alias or field.name) == field.wire
    for field in spec.scalar_fields:
        assert field.name in response.model_fields, (spec.name, field.name)
        assert (response.model_fields[field.name].alias or field.name) == field.wire


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


def test_sdk_method_returns_the_bound_coroutine_function(sdk):
    for spec in SPECS:
        bound = sdk_method(sdk, spec)
        assert isinstance(bound, types.MethodType)
        assert bound == getattr(getattr(sdk, spec.resource), spec.name)
        assert inspect.iscoroutinefunction(bound)


@pytest.mark.anyio
async def test_sdk_method_calls_the_upstream_service(sdk, upstream):
    upstream.route("/company.json", upstream.ok(corp_name="삼성전자", ceo_nm="Jun Young-hyun"))
    response = await sdk_method(sdk, "company")(corporation_code="00126380")
    assert response.corporation_name == "삼성전자"
    assert upstream.params("/company.json") == [{"corp_code": "00126380"}]
