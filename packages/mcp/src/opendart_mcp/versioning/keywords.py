"""Compare the leaf keywords of one JSON Schema node: descriptions, types, values, bounds.

Structural keywords that recurse (``properties``, ``additionalProperties``, ``items``) are
compared in ``schema``. Every function returns classified changes for one node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.versioning.levels import ABSENT, Level, show
from opendart_mcp.versioning.model import canonical

if TYPE_CHECKING:
    from collections.abc import Mapping

    from opendart_mcp.versioning.levels import At, Change

type Node = Mapping[str, object]

ANNOTATIONS: Final = frozenset(
    {"title", "description", "examples", "$comment", "deprecated", "readOnly", "writeOnly"}
)
LOWER_BOUNDS: Final = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
UPPER_BOUNDS: Final = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")
# Adding or changing one of these narrows the accepted values; removing it widens them.
RESTRICTIONS: Final = ("pattern", "format", "multipleOf", "uniqueItems")
UNIONS: Final = ("anyOf", "oneOf")
# Keywords that describe a whole node rather than one of its type branches.
NODE_LEVEL: Final = ANNOTATIONS | {"default", *UNIONS}
# Keywords compared within a branch. A branch holds anyOf or oneOf only when a union member is
# itself a union, whose changes are then classified as unknown keywords.
INTERPRETED: Final = ANNOTATIONS | {
    "default",
    "type",
    "enum",
    "const",
    "properties",
    "required",
    "additionalProperties",
    "items",
    *LOWER_BOUNDS,
    *UPPER_BOUNDS,
    *RESTRICTIONS,
}
_JSON_TYPES: Final = ((bool, "boolean"), (int, "integer"), (float, "number"), (str, "string"))


def transition(key: str, old: Node, new: Node) -> str:
    """Describe how one keyword changed.

    Args:
        key (str): Keyword.
        old (Node): Previous node.
        new (Node): Current node.

    Returns:
        str: ``key old -> new``.
    """
    return f"{key} {show(old.get(key, ABSENT))} -> {show(new.get(key, ABSENT))}"


def differs(key: str, old: Node, new: Node) -> bool:
    """Tell whether a keyword differs, counting absence as a value.

    Args:
        key (str): Keyword.
        old (Node): Previous node.
        new (Node): Current node.

    Returns:
        bool: True when the keyword was added, removed, or changed.
    """
    return old.get(key, ABSENT) != new.get(key, ABSENT)


def json_type(value: object) -> str:
    """Name the JSON type of a value.

    Args:
        value (object): JSON value.

    Returns:
        str: JSON Schema type name.
    """
    if value is None:
        return "null"
    for python_type, name in _JSON_TYPES:
        if isinstance(value, python_type):
            return name
    return "array" if isinstance(value, list) else "object"


def allowed_values(node: Node) -> dict[str, object] | None:
    """Collect a node's allowed values from ``enum`` or ``const``.

    Args:
        node (Node): Branch schema.

    Returns:
        dict[str, object] | None: Values by canonical JSON, or None when unrestricted.
    """
    values = node.get("enum")
    if isinstance(values, list):
        return {canonical(value): value for value in values}
    return {canonical(node["const"]): node["const"]} if "const" in node else None


def _without_null_default(node: Node) -> Node:
    """Treat ``default: null`` as no default; both mean the value may be omitted.

    Args:
        node (Node): Schema node.

    Returns:
        Node: The node without a null default.
    """
    if "default" in node and node["default"] is None:
        return {key: value for key, value in node.items() if key != "default"}
    return node


def compare_annotations(old: Node, new: Node, at: At) -> list[Change]:
    """Compare descriptive keywords and the default.

    Args:
        old (Node): Previous node.
        new (Node): Current node.
        at (At): Location.

    Returns:
        list[Change]: PATCH changes, and MINOR for a changed input default.
    """
    level = Level.MINOR if at.mode == "input" else Level.PATCH
    before, after = _without_null_default(old), _without_null_default(new)
    return [
        at.change(level if key == "default" else Level.PATCH, transition(key, before, after))
        for key in sorted(ANNOTATIONS | {"default"})
        if differs(key, before, after)
    ]


def union_keyword(node: Node) -> str | None:
    """Name the keyword that lists a node's alternatives.

    Args:
        node (Node): Schema node.

    Returns:
        str | None: ``anyOf`` or ``oneOf`` (``anyOf`` when both are present), or None.
    """
    return next((key for key in UNIONS if isinstance(node.get(key), list)), None)


def _beside(node: Node, union: str | None) -> Node:
    """Collect the keywords placed beside a node's alternatives.

    Args:
        node (Node): Schema node.
        union (str | None): The keyword listing its alternatives, if any.

    Returns:
        Node: Keywords other than the alternatives, descriptions, and the default; empty
        without alternatives.
    """
    if union is None:
        return {}
    skipped = ANNOTATIONS | {"default", union}
    return {key: value for key, value in node.items() if key not in skipped}


def compare_union_keywords(old: Node, new: Node, at: At) -> list[Change]:
    """Compare how a node combines alternatives, and keywords beside them, conservatively.

    ``oneOf`` rejects a value that more than one alternative accepts, so switching to or from
    it can change the accepted values while every alternative stays the same; ``anyOf`` and a
    list of types are equivalent. Keywords beside the alternatives, such as a discriminator or
    a second union, are not interpreted either.

    Args:
        old (Node): Previous node.
        new (Node): Current node.
        at (At): Location.

    Returns:
        list[Change]: Changes to the combining keyword and to keywords beside it.
    """
    was, now = union_keyword(old), union_keyword(new)
    changes: list[Change] = []
    if was != now and "oneOf" in {was, now}:
        detail = f"union keyword {was or "none"} -> {now or "none"}"
        changes.append(at.change(at.unknown(), detail))
    before, after = _beside(old, was), _beside(new, now)
    return changes + [
        at.change(at.unknown(), transition(key, before, after))
        for key in sorted(before.keys() | after.keys())
        if differs(key, before, after)
    ]


def compare_types(old: set[str], new: set[str], at: At, *, covered: set[str]) -> list[Change]:
    """Classify types that a node stopped or started allowing.

    Args:
        old (set[str]): Previous type names.
        new (set[str]): Current type names.
        at (At): Location.
        covered (set[str]): Previous types whose values a current branch still accepts, such
            as integers in a number branch; their branches are compared with that branch.

    Returns:
        list[Change]: Type changes.
    """
    removed, added = old - new, new - old
    if at.mode == "output":
        detail = f"type {sorted(old)} -> {sorted(new)}"
        return [at.change(Level.MAJOR, detail)] if removed | added else []
    return [
        at.change(Level.MAJOR, f"type {name!r} no longer accepted")
        for name in sorted(removed - covered)
    ] + [at.change(Level.MINOR, f"type {name!r} now accepted") for name in sorted(added)]


def compare_enum(old: Node, new: Node, at: At) -> list[Change]:
    """Compare allowed values.

    Args:
        old (Node): Previous branch.
        new (Node): Current branch.
        at (At): Location.

    Returns:
        list[Change]: Enum changes.
    """
    before, after = allowed_values(old), allowed_values(new)
    if before is None or after is None:
        if before is after:
            return []
        detail = "values restricted" if before is None else "value restriction removed"
        return [at.change(at.values(narrows=before is None), detail)]
    changes = [
        at.change(at.values(narrows=narrows), f"values {verb}: {show(values)}")
        for narrows, verb, values in (
            (True, "removed", [before[key] for key in sorted(before.keys() - after.keys())]),
            (False, "added", [after[key] for key in sorted(after.keys() - before.keys())]),
        )
        if values
    ]
    if not changes and list(before) != list(after):
        changes.append(at.change(Level.PATCH, "value order changed"))
    return changes


def _narrows(key: str, before: object, after: object) -> bool:
    """Tell whether a constraint change accepts fewer values.

    Args:
        key (str): Constraint keyword.
        before (object): Previous value, or ``ABSENT``.
        after (object): Current value, or ``ABSENT``.

    Returns:
        bool: True when the change tightens the constraint, and when unsure.
    """
    if key in RESTRICTIONS or before is ABSENT or after is ABSENT:
        return after is not ABSENT and after is not False
    if not isinstance(before, int | float) or not isinstance(after, int | float):
        return True
    return after > before if key in LOWER_BOUNDS else after < before


def compare_constraints(old: Node, new: Node, at: At) -> list[Change]:
    """Compare bounds and restricting keywords.

    Args:
        old (Node): Previous branch.
        new (Node): Current branch.
        at (At): Location.

    Returns:
        list[Change]: Constraint changes.
    """
    return [
        at.change(
            at.values(narrows=_narrows(key, old.get(key, ABSENT), new.get(key, ABSENT))),
            transition(key, old, new),
        )
        for key in (*LOWER_BOUNDS, *UPPER_BOUNDS, *RESTRICTIONS)
        if differs(key, old, new)
    ]


def compare_unknown(old: Node, new: Node, at: At) -> list[Change]:
    """Classify keywords this package does not interpret.

    Args:
        old (Node): Previous branch.
        new (Node): Current branch.
        at (At): Location.

    Returns:
        list[Change]: Conservatively classified changes.
    """
    return [
        at.change(at.unknown(), transition(key, old, new))
        for key in sorted((old.keys() | new.keys()) - INTERPRETED)
        if differs(key, old, new)
    ]
