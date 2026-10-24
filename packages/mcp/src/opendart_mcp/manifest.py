"""Component versions and fingerprints: build and check MCP component definitions.

``build_manifest`` reads every tool, resource, template, and prompt definition from a server
exactly as clients receive it, with hashes and token estimates. ``list_tools()`` and its
siblings run the server's middleware, which rewrites schemas the way the wire listing does,
and return every registered version. Definitions match the 2025-11-25 listing; 2026-07-28
listings omit a tool's ``execution`` because clients negotiate background tasks through the
tasks extension instead. Only ``_meta.fastmcp.versions`` is dropped: the protocol layer adds
it to the newest version of each name, so it changes whenever another version is
registered. The lifespan is never entered, so building a manifest needs no network or key.

``review`` compares the recorded lock, ``packages/mcp/components.lock.json``, with the
current server; ``scripts/check_mcp_components.py`` runs it. The framework-independent
rules live in ``opendart_mcp.versioning``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opendart_mcp.versioning.model import (
    ComponentFingerprint,
    ComponentRecord,
    Manifest,
    component_record,
    make_manifest,
    render_lock,
    server_record,
)
from opendart_mcp.versioning.policy import Finding, blocking, review

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fastmcp import FastMCP
    from pydantic import BaseModel

    from opendart_mcp.versioning.model import ComponentKind, Definition

__all__ = [
    "ComponentFingerprint",
    "ComponentRecord",
    "Finding",
    "Manifest",
    "blocking",
    "build_manifest",
    "component_fingerprints",
    "mark_optional",
    "render_lock",
    "review",
    "wire_definition",
]


def wire_definition(model: BaseModel) -> Definition:
    """Dump a protocol object as JSON without nulls or the volatile version list.

    Args:
        model (BaseModel): An ``mcp.types`` Tool, Resource, ResourceTemplate, or Prompt.

    Returns:
        Definition: The definition clients receive.
    """
    definition: Definition = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    meta = definition.get("_meta")
    fastmcp = meta.get("fastmcp") if isinstance(meta, dict) else None
    if isinstance(fastmcp, dict):
        fastmcp.pop("versions", None)
    return definition


def _identifier(key: str, kind: ComponentKind) -> str:
    """Extract the identifier from a component key such as ``template:a/{b}@1.0.0``.

    Args:
        key (str): FastMCP component key.
        kind (ComponentKind): Expected kind prefix.

    Returns:
        str: Name, URI, or URI template.
    """
    return key.removeprefix(f"{kind}:").rsplit("@", 1)[0]


def _records(
    kind: ComponentKind, items: Iterable[tuple[str, str | None, BaseModel]]
) -> dict[str, ComponentRecord]:
    """Fingerprint listed components of one kind.

    Args:
        kind (ComponentKind): Component kind.
        items (Iterable[tuple[str, str | None, BaseModel]]): Key, version, and protocol
            object of each component.

    Returns:
        dict[str, ComponentRecord]: Records by component key.
    """
    return {
        key: component_record(
            kind, _identifier(key, kind), version=version, definition=wire_definition(model)
        )
        for key, version, model in items
    }


async def build_manifest(server: FastMCP[Any]) -> Manifest:
    """Fingerprint every tool, resource, template, and prompt of a server.

    Args:
        server (FastMCP[Any]): Server to describe; its lifespan is not entered.

    Returns:
        Manifest: Definitions, hashes, token estimates, and server identity.
    """
    tools = await server.list_tools()
    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    prompts = await server.list_prompts()
    components = (
        _records("tool", ((t.key, t.version, t.to_mcp_tool()) for t in tools))
        | _records("resource", ((r.key, r.version, r.to_mcp_resource()) for r in resources))
        | _records("template", ((t.key, t.version, t.to_mcp_template()) for t in templates))
        | _records("prompt", ((p.key, p.version, p.to_mcp_prompt()) for p in prompts))
    )
    identity = server_record(server.name, server.version, server.instructions)
    return make_manifest(identity, components)


def mark_optional(full: Manifest, default: Manifest) -> Manifest:
    """Flag components that only an off-by-default setting registers.

    Args:
        full (Manifest): Manifest with every optional component enabled.
        default (Manifest): Manifest of the default configuration.

    Returns:
        Manifest: ``full`` with ``optional`` set on components missing from ``default``.

    Raises:
        ValueError: The default configuration has components the full one lacks.
    """
    extra = sorted(default.components.keys() - full.components.keys())
    if extra:
        message = f"Components missing from the full configuration: {", ".join(extra)}"
        raise ValueError(message)
    components = {
        key: record.model_copy(update={"optional": key not in default.components})
        for key, record in full.components.items()
    }
    return make_manifest(full.server, components)


def component_fingerprints(manifest: Manifest) -> list[ComponentFingerprint]:
    """List each component's key, version, and hash, for example for a status report.

    Args:
        manifest (Manifest): Manifest of the running server.

    Returns:
        list[ComponentFingerprint]: Fingerprints sorted by component key.
    """
    return [
        ComponentFingerprint(
            key=key,
            kind=record.kind,
            name=record.name,
            version=record.version,
            sha256=record.sha256,
        )
        for key, record in manifest.components.items()
    ]
