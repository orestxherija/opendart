"""Advertise compact, equivalent JSON schemas for tool inputs and outputs.

Pydantic writes every optional field as ``{"anyOf": [{"type": "integer"}, {"type": "null"}],
"default": null}``. The equivalent ``{"type": ["integer", "null"]}`` is a fraction of the
size, and tool definitions are paid for in context tokens. FastMCP validates arguments from
the function signature, not from the advertised schema, so only the description changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

from fastmcp.server.middleware import Middleware

if TYPE_CHECKING:
    from collections.abc import Sequence

    import mcp.types as mt
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools import Tool

type Schema = dict[str, Any]

_NULL = {"type": "null"}
# Keywords that constrain values of every type, so null could fail them after a merge.
_TYPE_INDEPENDENT = frozenset({"not", "allOf", "anyOf", "oneOf", "$ref", "if", "then", "else"})


def _merge_null(option: Schema) -> Schema | None:
    """Make one schema also accept null, when that can be said without ``anyOf``.

    Args:
        option (Schema): The non-null alternative.

    Returns:
        Schema | None: Equivalent nullable schema, or None when it needs ``anyOf``.
    """
    if _TYPE_INDEPENDENT & option.keys():
        return None
    if "const" in option:
        option = {**{k: v for k, v in option.items() if k != "const"}, "enum": [option["const"]]}
    kind = option.get("type")
    merged = {**option, "enum": [*option["enum"], None]} if "enum" in option else dict(option)
    if isinstance(kind, str):
        return {**merged, "type": [kind, "null"]}
    if isinstance(kind, list):
        return {**merged, "type": [*kind, "null"]}
    return merged if "enum" in option else None


def _compact_any_of(schema: Schema) -> Schema:
    """Collapse ``anyOf: [X, null]`` into a nullable X.

    Args:
        schema (Schema): Schema whose subschemas are already compact.

    Returns:
        Schema: Equivalent schema.
    """
    options = schema.get("anyOf")
    if not isinstance(options, list) or len(options) != 2 or _NULL not in options:  # noqa: PLR2004
        return schema
    other = options[0] if options[1] == _NULL else options[1]
    merged = _merge_null(other) if isinstance(other, dict) else None
    if merged is None:
        return schema
    rest = {key: value for key, value in schema.items() if key != "anyOf"}
    return {**merged, **rest}


def compact_schema(schema: Any) -> Any:
    """Rewrite a JSON schema into an equivalent, smaller one.

    Collapses nullable ``anyOf`` pairs, drops null defaults, and drops ``title`` keywords
    (titles repeat field names). Property names are never touched.

    Args:
        schema (Any): JSON schema, or any value nested in one.

    Returns:
        Any: Equivalent schema.
    """
    if isinstance(schema, list):
        return [compact_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    compacted: Schema = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            compacted[key] = {name: compact_schema(sub) for name, sub in value.items()}
        elif key == "title" or (key == "default" and value is None):
            continue
        else:
            compacted[key] = compact_schema(value)
    return _compact_any_of(compacted)


class CompactSchemaMiddleware(Middleware):
    """Advertise compact input and output schemas in ``tools/list``."""

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        """Compact every listed tool's schemas.

        Args:
            context (MiddlewareContext[mt.ListToolsRequest]): Request context.
            call_next (CallNext[mt.ListToolsRequest, Sequence[Tool]]): Rest of the chain.

        Returns:
            Sequence[Tool]: Tools with compact schemas.
        """
        tools = await call_next(context)
        return [
            tool.model_copy(
                update={
                    "parameters": compact_schema(tool.parameters),
                    "output_schema": compact_schema(tool.output_schema),
                }
            )
            for tool in tools
        ]
