"""Building component manifests from servers: wire fidelity, hashes, tokens, determinism."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from pydantic import BaseModel

from opendart_mcp.manifest import (
    build_manifest,
    component_fingerprints,
    mark_optional,
    render_lock,
    wire_definition,
)
from opendart_mcp.server import create_server
from opendart_mcp.settings import Settings, ToolSettings
from opendart_mcp.versioning.changes import parse_version
from opendart_mcp.versioning.model import approx_tokens, canonical, sha256

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/check_mcp_components.py"
BUDGET = 10_000


class Point(BaseModel):
    x: int
    label: str | None = None


class Shape(BaseModel):
    corners: list[Point]


def fake_server(*, versions=("1.0.0",), extra=False) -> FastMCP:
    server = FastMCP("Fake", version="0.0.1", instructions="Use the fake tools.")
    for version in versions:

        @server.tool(name="find", version=version, title="Find", tags={"b", "a"})
        async def find(query: str, limit: int = 5) -> Shape:
            """Find shapes by name."""
            return Shape(corners=[])

    if extra:

        @server.tool(name="extra", version="1.0.0")
        async def extra_tool() -> str:
            """An optional tool."""
            return "ok"

    @server.resource("fake://about", name="about", version="1.0.0", mime_type="text/plain")
    async def about() -> str:
        return "about"

    @server.resource("fake://items/{item_id}", name="item", version="1.0.0")
    async def item(item_id: str) -> str:
        return item_id

    @server.prompt(name="brief", version="1.0.0")
    def brief(company: str) -> str:
        """Brief a company.

        Args:
            company: Company name.
        """
        return company

    return server


@pytest.mark.anyio
async def test_manifest_lists_every_component_kind_with_its_identifier():
    manifest = await build_manifest(fake_server())
    assert {key: (r.kind, r.name, r.version) for key, r in manifest.components.items()} == {
        "prompt:brief@1.0.0": ("prompt", "brief", "1.0.0"),
        "resource:fake://about@1.0.0": ("resource", "fake://about", "1.0.0"),
        "template:fake://items/{item_id}@1.0.0": ("template", "fake://items/{item_id}", "1.0.0"),
        "tool:find@1.0.0": ("tool", "find", "1.0.0"),
    }
    assert list(manifest.components) == sorted(manifest.components)
    assert manifest.totals.counts == {"tool": 1, "resource": 1, "template": 1, "prompt": 1}


@pytest.mark.anyio
async def test_definitions_match_the_wire_listing():
    server = fake_server()
    manifest = await build_manifest(server)
    async with Client(server) as client:
        listed = {
            "tool:find@1.0.0": (await client.list_tools())[0],
            "resource:fake://about@1.0.0": (await client.list_resources())[0],
            "template:fake://items/{item_id}@1.0.0": (await client.list_resource_templates())[0],
            "prompt:brief@1.0.0": (await client.list_prompts())[0],
        }
    for key, model in listed.items():
        assert manifest.components[key].definition == wire_definition(model)


@pytest.mark.anyio
async def test_output_schemas_are_dereferenced_like_the_wire():
    manifest = await build_manifest(fake_server())
    output = manifest.components["tool:find@1.0.0"].definition["outputSchema"]
    assert "$defs" not in canonical(output)
    assert output["properties"]["corners"]["items"]["properties"]["x"] == {"type": "integer"}


@pytest.mark.anyio
async def test_every_version_is_recorded_without_the_volatile_version_list():
    manifest = await build_manifest(fake_server(versions=("1.0.0", "2.0.0")))
    for version in ("1.0.0", "2.0.0"):
        meta = manifest.components[f"tool:find@{version}"].definition["_meta"]
        assert meta == {"fastmcp": {"tags": ["a", "b"], "version": version}}


@pytest.mark.anyio
async def test_hashes_facets_and_tokens_follow_the_definition():
    record = (await build_manifest(fake_server())).components["tool:find@1.0.0"]
    definition = record.definition
    assert record.sha256 == sha256(definition)
    assert record.facets == {key: sha256(value) for key, value in definition.items()}
    assert {"description", "inputSchema", "outputSchema", "_meta"} <= set(record.facets)
    visible = {key: definition[key] for key in ("name", "title", "description", "inputSchema")}
    assert record.model_tokens == approx_tokens(canonical(visible))
    assert record.definition_tokens == approx_tokens(canonical(definition))
    assert record.definition_tokens > record.model_tokens  # the output schema is not model-visible


@pytest.mark.anyio
async def test_server_identity_and_instructions_are_fingerprinted():
    manifest = await build_manifest(fake_server())
    assert manifest.server.name == "Fake"
    assert manifest.server.version == "0.0.1"
    assert manifest.server.instructions_sha256 == sha256("Use the fake tools.")
    assert manifest.server.instructions_tokens == approx_tokens("Use the fake tools.")


@pytest.mark.anyio
async def test_optional_components_are_flagged_and_excluded_from_the_default_budget():
    full = await build_manifest(fake_server(extra=True))
    default = await build_manifest(fake_server())
    merged = mark_optional(full, default)
    assert merged.components["tool:extra@1.0.0"].optional is True
    assert merged.components["tool:find@1.0.0"].optional is False
    find = merged.components["tool:find@1.0.0"].model_tokens
    extra = merged.components["tool:extra@1.0.0"].model_tokens
    assert merged.totals.default_tool_model_tokens == find
    assert merged.totals.tool_model_tokens == find + extra


@pytest.mark.anyio
async def test_a_default_configuration_cannot_have_more_components():
    full = await build_manifest(fake_server())
    default = await build_manifest(fake_server(extra=True))
    with pytest.raises(ValueError, match=r"tool:extra@1\.0\.0"):
        mark_optional(full, default)


@pytest.mark.anyio
async def test_fingerprints_summarize_each_component():
    manifest = await build_manifest(fake_server())
    fingerprints = component_fingerprints(manifest)
    assert [f.key for f in fingerprints] == list(manifest.components)
    first = fingerprints[0]
    assert first.model_dump() == {
        "key": "prompt:brief@1.0.0",
        "kind": "prompt",
        "name": "brief",
        "version": "1.0.0",
        "sha256": manifest.components["prompt:brief@1.0.0"].sha256,
    }


@pytest.mark.anyio
async def test_rendering_is_deterministic_and_round_trips():
    first = render_lock(await build_manifest(fake_server()))
    second = render_lock(await build_manifest(fake_server()))
    assert first == second
    assert first.endswith("}\n")
    assert '"tool:find@1.0.0": {' in first


def test_wire_definition_keeps_meta_without_a_fastmcp_namespace():
    class Plain(BaseModel):
        name: str
        meta: dict[str, object] | None = None

    assert wire_definition(Plain(name="x", meta={"other": 1})) == {
        "name": "x",
        "meta": {"other": 1},
    }
    assert wire_definition(Plain(name="x")) == {"name": "x"}


def full_settings(*, optional: bool) -> Settings:
    return Settings(tools=ToolSettings(enable_service_tools=optional))


@pytest.mark.anyio
async def test_every_server_component_declares_a_semantic_version():
    manifest = await build_manifest(create_server(full_settings(optional=True)))
    unversioned = [k for k, r in manifest.components.items() if parse_version(r.version) is None]
    assert unversioned == []


@pytest.mark.anyio
async def test_default_tool_definitions_fit_the_token_budget():
    full = await build_manifest(create_server(full_settings(optional=True)))
    default = await build_manifest(create_server(full_settings(optional=False)))
    merged = mark_optional(full, default)
    assert merged.totals.default_tool_model_tokens <= BUDGET
    assert {r.name for r in merged.components.values() if r.optional} <= {
        "list_services",
        "call_service",
    }


async def wire_listing(server, mode):
    async with Client(server, mode=mode) as client:
        listed = {
            "tool": [(t.name, t) for t in await client.list_tools()],
            "resource": [(str(r.uri), r) for r in await client.list_resources()],
            "template": [(t.uri_template, t) for t in await client.list_resource_templates()],
            "prompt": [(p.name, p) for p in await client.list_prompts()],
        }
    return {
        f"{kind}:{name}@{model.meta["fastmcp"]["version"]}": wire_definition(model)
        for kind, models in listed.items()
        for name, model in models
    }


@pytest.mark.anyio
async def test_server_definitions_match_the_handshake_era_listing():
    server = create_server(full_settings(optional=True))
    manifest = await build_manifest(server)
    definitions = {key: record.definition for key, record in manifest.components.items()}
    assert await wire_listing(server, "legacy") == definitions


@pytest.mark.anyio
async def test_modern_listings_differ_only_in_task_execution():
    server = create_server(full_settings(optional=True))
    manifest = await build_manifest(server)
    without_execution = {
        key: {k: v for k, v in record.definition.items() if k != "execution"}
        for key, record in manifest.components.items()
    }
    assert await wire_listing(server, "auto") == without_execution


def test_the_lock_does_not_depend_on_hash_seeds(tmp_path):
    outputs = []
    for seed in ("1", "2"):
        lock = tmp_path / f"lock-{seed}.json"
        environment = {**os.environ, "PYTHONHASHSEED": seed}
        subprocess.run(  # noqa: S603 - fixed interpreter and repository script
            [sys.executable, str(SCRIPT), "--update", "--accept-changes", "--lock", str(lock)],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            timeout=60,
        )
        outputs.append(lock.read_bytes())
    assert outputs[0] == outputs[1]
