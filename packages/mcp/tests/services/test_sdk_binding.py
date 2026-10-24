"""The service catalog matches the SDK's methods, parameters, and models, and binds to them."""

from __future__ import annotations

import importlib
import inspect
import types
import typing
from typing import Any

import pytest
from pydantic import BaseModel

from opendart import OpenDARTError
from opendart_analysis.catalog import RESOURCES, SERVICES, SERVICE_NAMES, ServiceSpec
from opendart_mcp.services.sdk_binding import sdk_method

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
