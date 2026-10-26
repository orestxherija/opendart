"""Classify the differences between two JSON Schemas by what they can break.

Input schemas describe what clients send, so accepting fewer values (a removed or newly
required property, a removed type or enum value, a tighter bound or pattern) breaks callers
and needs a MAJOR version; accepting more is MINOR. Output schemas describe what clients
receive: a removed property or any change of a value's type needs MAJOR, other structural
changes MINOR. Descriptions, titles, and examples are PATCH. Keywords this package does not
interpret count as narrowing in input schemas, so the classification errs toward MAJOR.

Unions (``anyOf``/``oneOf``, or a list of types) are split into one branch per type, and
branches of the same type are compared keyword by keyword. A branch whose type is gone is
compared with the branch that now accepts its values: a number branch for integers, an untyped
branch for any type, so a tighter bound there still counts. Switching to or from ``oneOf``,
which rejects values that several alternatives accept, is not interpreted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.versioning.keywords import (
    NODE_LEVEL,
    allowed_values,
    compare_annotations,
    compare_constraints,
    compare_enum,
    compare_types,
    compare_union_keywords,
    compare_unknown,
    json_type,
    transition,
    union_keyword,
)
from opendart_mcp.versioning.levels import ABSENT, At, Level, show

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from opendart_mcp.versioning.levels import Change, Mode

type Node = Mapping[str, object]


def _flatten(node: Node) -> Node:
    """Merge a single ``allOf`` member into its parent, as Pydantic wraps references.

    Args:
        node (Node): Schema node.

    Returns:
        Node: Equivalent node without a one-member ``allOf``.
    """
    members = node.get("allOf")
    if isinstance(members, list) and len(members) == 1 and isinstance(members[0], dict):
        rest = {key: value for key, value in node.items() if key != "allOf"}
        return {**members[0], **rest}
    return node


def _type_name(node: Node) -> str:
    """Name the type of a node that declares none.

    Args:
        node (Node): Schema node without a string ``type``.

    Returns:
        str: Inferred type, or ``any``.
    """
    if "properties" in node:
        return "object"
    if "items" in node:
        return "array"
    allowed = allowed_values(node)
    names = {json_type(value) for value in allowed.values()} if allowed else set()
    return names.pop() if len(names) == 1 else "any"


def _fits(value: object, name: str) -> bool:
    """Tell whether a value has a type, counting integers as numbers.

    Args:
        value (object): JSON value.
        name (str): JSON Schema type name.

    Returns:
        bool: True when a schema of that type can accept the value.
    """
    kind = json_type(value)
    return kind == name or (name == "number" and kind == "integer")


_TYPE_KEYWORDS: Final[Mapping[str, frozenset[str]]] = {
    "object": frozenset(
        {
            "properties",
            "required",
            "additionalProperties",
            "patternProperties",
            "propertyNames",
            "minProperties",
            "maxProperties",
            "dependentRequired",
        }
    ),
    "array": frozenset({"items", "prefixItems", "minItems", "maxItems", "uniqueItems", "contains"}),
    "string": frozenset({"minLength", "maxLength", "pattern", "format"}),
    "number": frozenset(
        {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
    ),
}
_TYPE_SPECIFIC: Final = frozenset().union(*_TYPE_KEYWORDS.values())


def _restrict(name: str, branch: Node) -> Node | None:
    """Keep only the keywords and enum values that apply to a branch's type.

    ``{"type": ["string", "null"], "enum": ["a", null]}`` and ``anyOf: [{"type": "string",
    "enum": ["a"]}, {"type": "null"}]`` then yield the same branches, as do object keywords
    beside ``"type": ["object", "null"]``.

    Args:
        name (str): Branch type.
        branch (Node): Branch schema.

    Returns:
        Node | None: The branch, or None when its enum admits no value of its type.
    """
    if name == "any":
        return branch
    applicable = _TYPE_KEYWORDS.get("number" if name == "integer" else name, frozenset())
    kept: dict[str, object] = {
        key: value
        for key, value in branch.items()
        if key not in _TYPE_SPECIFIC or key in applicable
    }
    values = kept.get("enum")
    if not isinstance(values, list):
        return kept
    admitted = [value for value in values if _fits(value, name)]
    if not admitted:
        return None
    if name == "null":  # null is the only value of its type
        del kept["enum"]
    else:
        kept["enum"] = admitted
    return kept


_WIDER: Final[Mapping[str, tuple[str, ...]]] = {"integer": ("number", "any")}
"""Branch types that also accept a type's values; an untyped branch accepts every type."""


def _successor(name: str, new: Mapping[str, Node]) -> Node | None:
    """Find the current branch that accepts the values a previous branch's type allowed.

    Args:
        name (str): Previous branch key, such as ``integer`` or ``string#2``.
        new (Mapping[str, Node]): Current branches by key.

    Returns:
        Node | None: The branch with the same key, else a wider one restricted to the type
        (a number branch for integers, an untyped branch for any type), or None when no
        current branch accepts the type.
    """
    if name in new:
        return new[name]
    kind = name.partition("#")[0]
    for wider in _WIDER.get(kind, ("any",)):
        branch = _restrict(kind, new[wider]) if wider in new else None
        if branch is not None:
            return branch
    return None


def _typed(node: Node) -> list[tuple[str, Node]]:
    """Split a node into one branch per type, dropping branches no value can satisfy.

    Args:
        node (Node): Schema node or union member.

    Returns:
        list[tuple[str, Node]]: Type names with their branch schemas.
    """
    declared = node.get("type")
    pairs: list[tuple[str, Node]]
    if isinstance(declared, list):
        pairs = [(str(name), {**node, "type": name}) for name in declared]
    else:
        pairs = [(declared if isinstance(declared, str) else _type_name(node), node)]
    restricted = ((name, _restrict(name, branch)) for name, branch in pairs)
    return [(name, branch) for name, branch in restricted if branch is not None]


def _branches(node: Node) -> dict[str, Node]:
    """Index a node's alternatives by type; repeated types are numbered in order.

    Args:
        node (Node): Schema node, possibly with ``anyOf`` or ``oneOf``.

    Returns:
        dict[str, Node]: Branch schemas by type name.
    """
    union = union_keyword(node)
    members = node[union] if union is not None else None
    if isinstance(members, list):
        alternatives = [member for member in members if isinstance(member, dict)]
    else:
        alternatives = [{key: value for key, value in node.items() if key not in NODE_LEVEL}]
    branches: dict[str, Node] = {}
    for alternative in alternatives:
        for name, branch in _typed(alternative):
            key, number = name, 1
            while key in branches:
                number += 1
                key = f"{name}#{number}"
            branches[key] = branch
    return branches


def _mapping(value: object) -> dict[str, object]:
    """Read a JSON object, or nothing.

    Args:
        value (object): Possibly a JSON object.

    Returns:
        dict[str, object]: The object, or an empty one.
    """
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _names(value: object) -> set[str]:
    """Read a list of property names, or nothing.

    Args:
        value (object): Possibly a list of names.

    Returns:
        set[str]: The names.
    """
    return {str(item) for item in value} if isinstance(value, list) else set()


def _properties(old: Node, new: Node, at: At) -> list[Change]:
    """Compare object properties and which of them are required.

    Args:
        old (Node): Previous branch.
        new (Node): Current branch.
        at (At): Location.

    Returns:
        list[Change]: Property changes, including nested ones.
    """
    before, after = _mapping(old.get("properties")), _mapping(new.get("properties"))
    was, now = _names(old.get("required")), _names(new.get("required"))
    changes = [
        at.below(f".{name}").change(Level.MAJOR, "property removed")
        for name in sorted(before.keys() - after.keys())
    ]
    for name in sorted(after.keys() - before.keys()):
        kind = "required" if name in now else "optional"
        level = at.values(narrows=name in now)
        changes.append(at.below(f".{name}").change(level, f"{kind} property added"))
    for name in sorted(before.keys() & after.keys()):
        here = at.below(f".{name}")
        if (name in was) != (name in now):
            detail = "now required" if name in now else "no longer required"
            changes.append(here.change(at.values(narrows=name in now), detail))
        changes += diff_schema(before[name], after[name], mode=at.mode, path=here.path)
    return changes


def _additional(old: Node, new: Node, at: At) -> list[Change]:
    """Compare ``additionalProperties``; absent means any property is allowed.

    Args:
        old (Node): Previous branch.
        new (Node): Current branch.
        at (At): Location.

    Returns:
        list[Change]: Changes to undeclared properties.
    """
    before, after = old.get("additionalProperties", True), new.get("additionalProperties", True)
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return diff_schema(before, after, mode=at.mode, path=at.below(".*").path)
    narrows = after is False or (before is True and isinstance(after, dict))
    detail = f"additionalProperties {show(before)} -> {show(after)}"
    return [at.change(at.values(narrows=narrows), detail)]


def _items(old: Node, new: Node, at: At) -> list[Change]:
    """Compare array item schemas.

    Args:
        old (Node): Previous branch.
        new (Node): Current branch.
        at (At): Location.

    Returns:
        list[Change]: Item changes.
    """
    before, after = old.get("items", ABSENT), new.get("items", ABSENT)
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return diff_schema(before, after, mode=at.mode, path=at.below("[]").path)
    return [at.below("[]").change(at.unknown(), transition("items", old, new))]


_BRANCH_CHECKS: Final[tuple[Callable[[Node, Node, At], list[Change]], ...]] = (
    compare_annotations,
    compare_enum,
    compare_constraints,
    _properties,
    _additional,
    _items,
    compare_unknown,
)


def diff_schema(old: object, new: object, *, mode: Mode, path: str) -> list[Change]:
    """Classify every difference between two schema nodes.

    Args:
        old (object): Previous schema node.
        new (object): Current schema node.
        mode (Mode): ``input`` for what clients send, ``output`` for what they receive.
        path (str): Location for messages, such as ``inputSchema``.

    Returns:
        list[Change]: Classified changes; empty when the schemas are equal.
    """
    at = At(mode, path)
    if old == new:
        return []
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [at.change(Level.MAJOR, f"schema {show(old)} -> {show(new)}")]
    before, after = _flatten(old), _flatten(new)
    changes = compare_annotations(before, after, at) + compare_union_keywords(before, after, at)
    old_branches, new_branches = _branches(before), _branches(after)
    pairs = {
        name: (branch, successor)
        for name, branch in old_branches.items()
        if (successor := _successor(name, new_branches)) is not None
    }
    changes += compare_types(set(old_branches), set(new_branches), at, covered=set(pairs))
    several = len(old_branches) > 1 or len(new_branches) > 1
    for name, (branch, successor) in sorted(pairs.items()):
        where = at.below(f"<{name}>") if several else at
        for check in _BRANCH_CHECKS:
            changes += check(branch, successor, where)
    return changes
