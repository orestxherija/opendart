"""Records of the component lock and the hashing and token rules behind them.

Everything here is framework-independent: definitions are the JSON objects a client receives
from ``tools/list``, ``resources/list``, ``resources/templates/list``, and ``prompts/list``.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

type ComponentKind = Literal["tool", "resource", "template", "prompt"]
type Definition = dict[str, JsonValue]

LOCK_FORMAT: Final = 1
KINDS: Final[tuple[ComponentKind, ...]] = ("tool", "resource", "template", "prompt")

# Parts of a definition that reach the model's context. Tools are always in context; the
# model never sees output schemas. Other kinds reach it only when a host shows them.
MODEL_VISIBLE: Final[Mapping[ComponentKind, tuple[str, ...]]] = {
    "tool": ("name", "title", "description", "inputSchema"),
    "resource": ("name", "title", "description", "uri", "mimeType"),
    "template": ("name", "title", "description", "uriTemplate", "mimeType"),
    "prompt": ("name", "title", "description", "arguments"),
}


def canonical(value: object) -> str:
    """Serialize JSON deterministically: sorted keys, no whitespace, characters kept.

    Args:
        value (object): JSON-compatible value.

    Returns:
        str: Canonical JSON text.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(value: object) -> str:
    """Hash the canonical JSON of a value.

    Args:
        value (object): JSON-compatible value.

    Returns:
        str: Hex SHA-256 of the UTF-8 canonical JSON.
    """
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def approx_tokens(text: str) -> int:
    """Estimate tokens at about four characters each; stable, not a real tokenizer.

    Args:
        text (str): Text as the model would receive it.

    Returns:
        int: Estimated token count, rounded up.
    """
    return (len(text) + 3) // 4


class Record(BaseModel):
    """Base for immutable lock records that reject unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ComponentRecord(Record):
    """One component definition with its fingerprint and size.

    Attributes:
        kind (ComponentKind): Tool, resource, template, or prompt.
        name (str): Identifier: the name of a tool or prompt, the URI of a resource, or the
            URI template of a template.
        version (str | None): Declared component version.
        sha256 (str): Hash of the whole definition.
        facets (dict[str, str]): Hash of each top-level part of the definition.
        model_tokens (int): Estimated tokens of the model-visible parts.
        definition_tokens (int): Estimated tokens of the whole definition.
        optional (bool): Registered only when an off-by-default setting is enabled.
        definition (Definition): The definition as clients receive it.
    """

    kind: ComponentKind
    name: str
    version: str | None = None
    sha256: str
    facets: dict[str, str]
    model_tokens: int
    definition_tokens: int
    optional: bool = False
    definition: Definition


class ServerRecord(Record):
    """Server identity and the instructions every client receives.

    Attributes:
        name (str): Server name.
        version (str | None): Server version reported to clients.
        instructions_sha256 (str): Hash of the instructions text.
        instructions_tokens (int): Estimated tokens of the instructions.
    """

    name: str
    version: str | None = None
    instructions_sha256: str
    instructions_tokens: int


class Totals(Record):
    """Counts and token estimates derived from the components.

    Attributes:
        counts (dict[str, int]): Components by kind, all configurations.
        default_tool_model_tokens (int): Model-visible tool tokens with optional tools off.
        tool_model_tokens (int): Model-visible tool tokens with every tool registered.
        definition_tokens (int): Tokens of every definition, for reference.
    """

    counts: dict[str, int]
    default_tool_model_tokens: int
    tool_model_tokens: int
    definition_tokens: int


class Manifest(Record):
    """Every component definition of a server, as recorded in the component lock.

    Attributes:
        format (int): Lock layout version.
        server (ServerRecord): Server identity and instructions.
        totals (Totals): Derived counts and token estimates.
        components (dict[str, ComponentRecord]): Records keyed like ``tool:name@1.0.0``.
    """

    format: int = LOCK_FORMAT
    server: ServerRecord
    totals: Totals
    components: dict[str, ComponentRecord]


class ComponentFingerprint(Record):
    """A component's identity and definition hash, small enough for a status report.

    Attributes:
        key (str): Component key, such as ``tool:find_company@1.0.0``.
        kind (ComponentKind): Component kind.
        name (str): Component identifier.
        version (str | None): Declared version.
        sha256 (str): Definition hash, comparable with the component lock.
    """

    key: str
    kind: ComponentKind
    name: str
    version: str | None
    sha256: str


def component_record(
    kind: ComponentKind, name: str, *, version: str | None, definition: Definition
) -> ComponentRecord:
    """Fingerprint one definition.

    Args:
        kind (ComponentKind): Component kind.
        name (str): Component identifier.
        version (str | None): Declared version.
        definition (Definition): Definition as clients receive it.

    Returns:
        ComponentRecord: Record with hashes and token estimates.
    """
    visible = {key: definition[key] for key in MODEL_VISIBLE[kind] if key in definition}
    return ComponentRecord(
        kind=kind,
        name=name,
        version=version,
        sha256=sha256(definition),
        facets={key: sha256(value) for key, value in definition.items()},
        model_tokens=approx_tokens(canonical(visible)),
        definition_tokens=approx_tokens(canonical(definition)),
        definition=definition,
    )


def server_record(name: str, version: str | None, instructions: str | None) -> ServerRecord:
    """Describe the server.

    Args:
        name (str): Server name.
        version (str | None): Server version.
        instructions (str | None): Server instructions.

    Returns:
        ServerRecord: Identity with the instructions fingerprint.
    """
    text = instructions or ""
    return ServerRecord(
        name=name,
        version=version,
        instructions_sha256=sha256(text),
        instructions_tokens=approx_tokens(text),
    )


def totals(components: Iterable[ComponentRecord]) -> Totals:
    """Summarize component counts and token estimates.

    Args:
        components (Iterable[ComponentRecord]): Records to summarize.

    Returns:
        Totals: Counts by kind and token sums.
    """
    records = list(components)
    tools = [record for record in records if record.kind == "tool"]
    return Totals(
        counts={kind: sum(1 for r in records if r.kind == kind) for kind in KINDS},
        default_tool_model_tokens=sum(r.model_tokens for r in tools if not r.optional),
        tool_model_tokens=sum(r.model_tokens for r in tools),
        definition_tokens=sum(r.definition_tokens for r in records),
    )


def make_manifest(server: ServerRecord, components: Mapping[str, ComponentRecord]) -> Manifest:
    """Assemble a manifest with sorted components and fresh totals.

    Args:
        server (ServerRecord): Server identity.
        components (Mapping[str, ComponentRecord]): Records by component key.

    Returns:
        Manifest: Manifest ready to compare or write.
    """
    ordered = dict(sorted(components.items()))
    return Manifest(server=server, totals=totals(ordered.values()), components=ordered)


def render_lock(manifest: Manifest) -> str:
    """Render the lock file: sorted keys, two-space indent, characters kept, final newline.

    Args:
        manifest (Manifest): Manifest to write.

    Returns:
        str: File contents; equal manifests always render identically.
    """
    data = manifest.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
