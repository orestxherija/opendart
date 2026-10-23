"""Output-model contract: structured content drops nulls, so nullable fields need defaults.

A required field that may be None would vanish from structured content while the output
schema still requires it, and clients that validate structured content would reject the
result. Both the registered models and the published output schemas are checked.
"""

from __future__ import annotations

import inspect
import types
import typing

import pytest
from pydantic import BaseModel

from opendart_mcp.manifest import build_manifest
from opendart_mcp.server import create_server
from opendart_mcp.settings import Settings, ToolSettings


def models_in(annotation):
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for argument in typing.get_args(annotation):
        yield from models_in(argument)


def admits_none(annotation):
    if annotation in {None, type(None), typing.Any, object}:
        return True
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return admits_none(typing.get_args(annotation)[0])
    if origin in {typing.Union, types.UnionType}:
        return any(admits_none(argument) for argument in typing.get_args(annotation))
    return False


def reachable_models(roots):
    seen, pending = {}, list(roots)
    while pending:
        model = pending.pop()
        name = f"{model.__module__}.{model.__qualname__}"
        if name in seen:
            continue
        seen[name] = model
        for field in model.model_fields.values():
            pending.extend(models_in(field.annotation))
    return seen


def nullable(schema):
    if not isinstance(schema, dict):
        return False
    declared = schema.get("type")
    if declared == "null" or (isinstance(declared, list) and "null" in declared):
        return True
    return any(nullable(branch) for branch in schema.get("anyOf", schema.get("oneOf", [])))


def required_nullable(schema, path):
    if not isinstance(schema, dict):
        return
    required = set(schema.get("required", []))
    for name, child in schema.get("properties", {}).items():
        if name in required and nullable(child):
            yield f"{path}.{name}"
        yield from required_nullable(child, f"{path}.{name}")
    for key, suffix in (("items", "[]"), ("additionalProperties", ".*")):
        yield from required_nullable(schema.get(key), path + suffix)
    for index, branch in enumerate(schema.get("anyOf", schema.get("oneOf", []))):
        yield from required_nullable(branch, f"{path}<{index}>")


@pytest.fixture
def server():
    return create_server(Settings(tools=ToolSettings(enable_service_tools=True)))


@pytest.mark.anyio
async def test_every_output_model_gives_nullable_fields_a_default(server):
    roots = []
    for registered in await server.list_tools():
        function = getattr(registered, "fn", None)
        if function is not None:
            roots += models_in(inspect.signature(function, eval_str=True).return_annotation)
    models = reachable_models(roots)
    assert len(models) >= len(roots) > 0
    violations = sorted(
        f"{name}.{field_name}"
        for name, model in models.items()
        for field_name, field in model.model_fields.items()
        if admits_none(field.annotation) and field.is_required()
    )
    assert violations == []


@pytest.mark.anyio
async def test_no_output_schema_requires_a_nullable_property(server):
    manifest = await build_manifest(server)
    violations = [
        violation
        for key, record in manifest.components.items()
        if record.kind == "tool"
        for violation in required_nullable(record.definition.get("outputSchema"), key)
    ]
    assert violations == []


class Inner(BaseModel):
    value: int | None


class Outer(BaseModel):
    inner: list[Inner]
    label: typing.Annotated[str | None, "meta"] = None
    extra: dict[str, Inner] | None = None


def test_the_contract_helpers_find_nested_violations():
    models = reachable_models([Outer])
    assert {model.__name__ for model in models.values()} == {"Outer", "Inner"}
    assert admits_none(Inner.model_fields["value"].annotation)
    assert admits_none(Outer.model_fields["label"].annotation)
    assert not admits_none(Outer.model_fields["inner"].annotation)
    schema = Outer.model_json_schema()
    inner = schema["$defs"]["Inner"]
    assert list(required_nullable(inner, "Inner")) == ["Inner.value"]
    assert not nullable("not a schema")
    assert list(required_nullable(None, "x")) == []
