"""JSON Schema diff: every rule of the input and output classification."""

from __future__ import annotations

import pytest

from opendart_mcp.versioning.levels import Change, Level, required_level, show
from opendart_mcp.versioning.schema import diff_schema

MAJOR, MINOR, PATCH, NONE = Level.MAJOR, Level.MINOR, Level.PATCH, Level.NONE


def obj(properties, required=(), **extra):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
        **extra,
    }


def nullable(schema, **extra):
    return {"anyOf": [schema, {"type": "null"}], "default": None, **extra}


STRING = {"type": "string"}
INTEGER = {"type": "integer"}


def level(old, new, mode="input"):
    return required_level(diff_schema(old, new, mode=mode, path="s"))


def details(old, new, mode="input"):
    return [(c.level, c.path, c.detail) for c in diff_schema(old, new, mode=mode, path="s")]


def test_equal_schemas_have_no_changes():
    schema = obj({"a": STRING}, ["a"])
    assert diff_schema(schema, dict(schema), mode="input", path="s") == []
    assert level(schema, schema) is NONE


@pytest.mark.parametrize("mode", ["input", "output"])
@pytest.mark.parametrize("key", ["description", "title", "examples", "deprecated"])
def test_descriptive_keywords_are_patch(mode, key):
    old = {**STRING, key: "old"}
    assert details(old, {**STRING, key: "new"}, mode) == [(PATCH, "s", f'{key} "old" -> "new"')]


def test_a_changed_default_is_minor_for_input_and_patch_for_output():
    old, new = {**INTEGER, "default": 5}, {**INTEGER, "default": 10}
    assert level(old, new, "input") is MINOR
    assert level(old, new, "output") is PATCH


@pytest.mark.parametrize(
    ("old", "new", "expected", "detail"),
    [
        (obj({"a": STRING, "b": STRING}), obj({"a": STRING}), MAJOR, "property removed"),
        (obj({"a": STRING}), obj({"a": STRING, "b": STRING}), MINOR, "optional property added"),
        (
            obj({"a": STRING}),
            obj({"a": STRING, "b": STRING}, ["b"]),
            MAJOR,
            "required property added",
        ),
        (obj({"a": STRING}), obj({"a": STRING}, ["a"]), MAJOR, "now required"),
        (obj({"a": STRING}, ["a"]), obj({"a": STRING}), MINOR, "no longer required"),
    ],
)
def test_input_properties(old, new, expected, detail):
    changes = diff_schema(old, new, mode="input", path="inputSchema")
    assert required_level(changes) is expected
    assert any(c.detail == detail and c.path.startswith("inputSchema.") for c in changes)


def test_a_renamed_input_property_is_a_removal_and_an_addition():
    changes = details(obj({"query": STRING}, ["query"]), obj({"text": STRING}, ["text"]))
    assert changes == [
        (MAJOR, "s.query", "property removed"),
        (MAJOR, "s.text", "required property added"),
    ]


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (obj({"a": STRING, "b": STRING}), obj({"a": STRING}), MAJOR),
        (obj({"a": STRING}), obj({"a": STRING, "b": STRING}, ["b"]), MINOR),
        (obj({"a": STRING}), obj({"a": STRING}, ["a"]), MINOR),
        (obj({"a": STRING}, ["a"]), obj({"a": STRING}), MINOR),
    ],
)
def test_output_properties(old, new, expected):
    assert level(old, new, "output") is expected


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (nullable(STRING), STRING, MAJOR),  # null no longer accepted
        (STRING, nullable(STRING), MINOR),  # null now accepted
        (INTEGER, {"type": "number"}, MINOR),  # every integer is a number
        ({"type": "number"}, INTEGER, MAJOR),
        (STRING, INTEGER, MAJOR),
        ({}, STRING, MAJOR),  # any value -> strings only
        (STRING, {}, MINOR),
        ({"type": ["string", "null"]}, STRING, MAJOR),
    ],
)
def test_input_types(old, new, expected):
    assert level(old, new) is expected


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (nullable(STRING), STRING),
        (STRING, nullable(STRING)),
        (INTEGER, {"type": "number"}),
        (STRING, INTEGER),
    ],
)
def test_any_output_type_change_is_major(old, new):
    assert level(old, new, "output") is MAJOR


def test_type_changes_name_the_types():
    assert details(STRING, nullable(STRING), "output") == [
        (MAJOR, "s", "type ['string'] -> ['null', 'string']")
    ]
    assert (MAJOR, "s", "type 'null' no longer accepted") in details(nullable(STRING), STRING)


def test_branches_of_a_union_are_compared_by_type():
    old = nullable({"type": "string", "maxLength": 10})
    new = nullable({"type": "string", "maxLength": 5})
    assert details(old, new) == [(MAJOR, "s<string>", "maxLength 10 -> 5")]


def enum(*values):
    return {"type": "string", "enum": list(values)}


@pytest.mark.parametrize(
    ("old", "new", "input_level", "output_level"),
    [
        (enum("a", "b"), enum("a"), MAJOR, MINOR),
        (enum("a"), enum("a", "b"), MINOR, MINOR),
        (STRING, enum("a"), MAJOR, MINOR),
        (enum("a"), STRING, MINOR, MINOR),
        (enum("a", "b"), enum("b", "a"), PATCH, PATCH),
        ({"const": "a"}, {"const": "b"}, MAJOR, MINOR),
    ],
)
def test_enums(old, new, input_level, output_level):
    assert level(old, new, "input") is input_level
    assert level(old, new, "output") is output_level


def test_enum_details_list_the_values():
    assert details(enum("a", "b", "c"), enum("a", "d")) == [
        (MAJOR, "s", 'values removed: ["b","c"]'),
        (MINOR, "s", 'values added: ["d"]'),
    ]


ARRAY = {"type": "array", "items": STRING}


@pytest.mark.parametrize(
    ("base", "old", "new", "expected"),
    [
        (STRING, {"maxLength": 10}, {"maxLength": 5}, MAJOR),
        (STRING, {"maxLength": 5}, {"maxLength": 10}, MINOR),
        (INTEGER, {"minimum": 1}, {"minimum": 2}, MAJOR),
        (INTEGER, {"minimum": 2}, {"minimum": 1}, MINOR),
        (INTEGER, {}, {"maximum": 50}, MAJOR),
        (INTEGER, {"maximum": 50}, {}, MINOR),
        (ARRAY, {"maxItems": 20}, {"maxItems": 10}, MAJOR),
        ({"type": "number"}, {"exclusiveMinimum": 0}, {"exclusiveMinimum": 1}, MAJOR),
        (STRING, {"minLength": "x"}, {"minLength": 1}, MAJOR),  # not comparable: assume narrower
        (STRING, {}, {"pattern": "^a"}, MAJOR),
        (STRING, {"pattern": "^a"}, {"pattern": "^b"}, MAJOR),
        (STRING, {"pattern": "^a"}, {}, MINOR),
        (STRING, {}, {"format": "date"}, MAJOR),
        (STRING, {"format": "date"}, {}, MINOR),
        (ARRAY, {}, {"uniqueItems": True}, MAJOR),
        (ARRAY, {"uniqueItems": True}, {"uniqueItems": False}, MINOR),
    ],
)
def test_input_constraints(base, old, new, expected):
    assert level({**base, **old}, {**base, **new}) is expected


def test_output_constraints_are_minor():
    assert level({**STRING, "maxLength": 10}, {**STRING, "maxLength": 5}, "output") is MINOR
    assert level(STRING, {**STRING, "pattern": "^a"}, "output") is MINOR


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (True, False, MAJOR),
        (False, True, MINOR),
        (True, STRING, MAJOR),
        (STRING, True, MINOR),
        (False, STRING, MINOR),
    ],
)
def test_additional_properties(old, new, expected):
    before = {"type": "object", "additionalProperties": old}
    assert level(before, {"type": "object", "additionalProperties": new}) is expected


def test_missing_additional_properties_means_any():
    assert level({"type": "object"}, {"type": "object", "additionalProperties": True}) is NONE
    assert level({"type": "object"}, {"type": "object", "additionalProperties": False}) is MAJOR


def test_mapping_values_are_compared_recursively():
    old = {"type": "object", "additionalProperties": INTEGER}
    new = {"type": "object", "additionalProperties": nullable(INTEGER)}
    assert details(old, new, "output")[-1] == (
        MAJOR,
        "s.*",
        "type ['integer'] -> ['integer', 'null']",
    )


def test_nested_items_report_their_path():
    old = obj({"rows": {"type": "array", "items": obj({"a": STRING, "b": STRING})}})
    new = obj({"rows": {"type": "array", "items": obj({"a": STRING})}})
    assert details(old, new, "output") == [(MAJOR, "s.rows[].b", "property removed")]


def test_items_that_are_not_schemas_are_compared_conservatively():
    old = {"type": "array", "items": STRING}
    new = {"type": "array", "items": False}
    assert details(old, new) == [(MAJOR, "s[]", 'items {"type":"string"} -> false')]
    assert level(old, {"type": "array"}, "output") is MINOR


@pytest.mark.parametrize(("mode", "expected"), [("input", MAJOR), ("output", MINOR)])
def test_unknown_keywords_are_conservative(mode, expected):
    old = {"type": "object", "propertyNames": {"pattern": "^a"}}
    new = {"type": "object", "propertyNames": {"pattern": "^b"}}
    assert level(old, new, mode) is expected


def test_keywords_beside_a_union_are_compared():
    old = {
        "oneOf": [obj({"a": STRING}), obj({"b": STRING})],
        "discriminator": {"propertyName": "a"},
    }
    new = {**old, "discriminator": {"propertyName": "b"}}
    assert details(old, new) == [
        (MAJOR, "s", 'discriminator {"propertyName":"a"} -> {"propertyName":"b"}')
    ]


def test_repeated_types_in_a_union_are_paired_in_order():
    old = {"anyOf": [obj({"a": STRING}), obj({"b": STRING})]}
    new = {"anyOf": [obj({"a": STRING}), obj({"c": STRING})]}
    assert details(old, new) == [
        (MAJOR, "s<object#2>.b", "property removed"),
        (MINOR, "s<object#2>.c", "optional property added"),
    ]


def test_types_are_inferred_when_undeclared():
    assert level({"properties": {"a": STRING}}, {"properties": {}}) is MAJOR
    assert level({"items": STRING}, {"items": INTEGER}) is MAJOR
    assert level({"enum": [1, 2]}, {"enum": [1]}) is MAJOR
    assert level({"enum": [1, "a"]}, {"enum": [1, "a", None]}) is MINOR


def test_a_single_all_of_is_merged_into_its_node():
    inner = obj({"a": STRING})
    assert level({"allOf": [inner], "description": "x"}, {**inner, "description": "x"}) is NONE


def test_boolean_schemas_are_compared_as_values():
    assert details(True, STRING) == [(MAJOR, "s", 'schema true -> {"type":"string"}')]


def test_required_level_and_rendering():
    changes = [Change(PATCH, "a", "x"), Change(MAJOR, "b", "y")]
    assert required_level(changes) is MAJOR
    assert required_level([]) is NONE
    assert str(changes[1]) == "b: y"
    assert show("x" * 100).endswith("...")
    assert len(show("x" * 100)) == 60


def test_enum_values_of_any_json_type_infer_a_type():
    assert level({"enum": [[1], [2]]}, {"enum": [[1]]}) is MAJOR
    assert level({"enum": [{"a": 1}]}, {"enum": [{"a": 1}, {"a": 2}]}) is MINOR


@pytest.mark.parametrize("mode", ["input", "output"])
def test_equivalent_nullable_forms_compare_equal(mode):
    pydantic = {
        "anyOf": [{"type": "string", "enum": ["KOSPI", "KOSDAQ"]}, {"type": "null"}],
        "default": None,
    }
    compact = {"type": ["string", "null"], "enum": ["KOSPI", "KOSDAQ", None]}
    assert diff_schema(pydantic, compact, mode=mode, path="s") == []
    assert diff_schema(nullable(INTEGER), {"type": ["integer", "null"]}, mode=mode, path="s") == []


def test_enum_values_outside_a_branch_type_are_ignored():
    # null fails the enum, so the null type admits nothing.
    assert level({"type": ["string", "null"], "enum": ["a"]}, enum("a")) is NONE
    # 2.5 can never be an integer.
    assert level({"type": "integer", "enum": [1, 2.5]}, {"type": "integer", "enum": [1]}) is NONE
    assert level({"type": "number", "enum": [1, 2.5]}, {"type": "number", "enum": [1]}) is MAJOR


@pytest.mark.parametrize("mode", ["input", "output"])
def test_a_null_default_is_no_default(mode):
    assert level({**STRING, "default": None}, STRING, mode) is NONE
    assert level({**STRING, "default": None}, {**STRING, "default": "x"}, mode) > NONE


@pytest.mark.parametrize("mode", ["input", "output"])
def test_type_specific_keywords_apply_only_to_their_type(mode):
    company = obj({"corp_code": STRING}, ["corp_code"])
    assert (
        diff_schema(nullable(company), {**company, "type": ["object", "null"]}, mode=mode, path="s")
        == []
    )
    dated = {"type": "string", "format": "date", "maxLength": 10}
    assert (
        diff_schema(nullable(dated), {**dated, "type": ["string", "null"]}, mode=mode, path="s")
        == []
    )
    bounded = {"type": "integer", "minimum": 1}
    assert (
        diff_schema(
            nullable(bounded), {**bounded, "type": ["integer", "null"]}, mode=mode, path="s"
        )
        == []
    )


def test_keywords_of_other_types_are_ignored_within_a_branch():
    assert level({**STRING, "minimum": 1}, {**STRING, "minimum": 5}) is NONE
    assert level({**INTEGER, "maxLength": 1}, INTEGER) is NONE


NUMBER = {"type": "number"}


@pytest.mark.parametrize(
    ("old", "new", "expected", "detail"),
    [
        # 75 was an accepted integer and is now above the maximum.
        ({**INTEGER, "maximum": 100}, {**NUMBER, "maximum": 50}, MAJOR, "maximum 100 -> 50"),
        ({**INTEGER}, {**NUMBER, "multipleOf": 0.5, "minimum": 10}, MAJOR, "minimum none -> 10"),
        (
            {**INTEGER, "maximum": 100},
            {**NUMBER, "maximum": 100},
            MINOR,
            "type 'number' now accepted",
        ),
        ({**INTEGER, "maximum": 50}, {**NUMBER, "maximum": 100}, MINOR, "maximum 50 -> 100"),
        ({**INTEGER, "enum": [1, 2]}, {**NUMBER, "enum": [1, 2.5]}, MAJOR, "values removed: [2]"),
        ({**INTEGER}, {**NUMBER, "enum": [1.5]}, MAJOR, "type 'integer' no longer accepted"),
    ],
)
def test_an_integer_that_becomes_a_number_keeps_its_bounds(old, new, expected, detail):
    changes = diff_schema(old, new, mode="input", path="s")
    assert required_level(changes) is expected
    assert detail in [change.detail for change in changes]


def test_integer_branches_are_compared_with_the_number_branch_that_replaces_them():
    old, new = nullable({**INTEGER, "maximum": 100}), nullable({**NUMBER, "maximum": 50})
    assert (MAJOR, "s<integer>", "maximum 100 -> 50") in details(old, new)
    both = {"anyOf": [{**INTEGER, "maximum": 100}, {**NUMBER, "maximum": 10}]}
    assert (MAJOR, "s<integer>", "maximum 100 -> 10") in details(both, {**NUMBER, "maximum": 10})
    assert level({**INTEGER, "maximum": 100}, {**NUMBER, "maximum": 50}, "output") is MAJOR


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ({**INTEGER, "maximum": 100}, {"maximum": 50}, MAJOR),  # untyped, but bounded
        ({**STRING, "maxLength": 5}, {"maxLength": 3, "minimum": 1}, MAJOR),
        ({**STRING, "maxLength": 5}, {"minimum": 1}, MINOR),  # minimum ignores strings
        ({"type": "boolean"}, {"enum": [1, "a"]}, MAJOR),  # no boolean is allowed any more
        ({"anyOf": [{"not": STRING}, {"not": INTEGER}]}, {"anyOf": [{"not": STRING}]}, MAJOR),
    ],
)
def test_a_type_absorbed_by_an_untyped_branch_is_compared_with_it(old, new, expected):
    assert level(old, new) is expected


ONE_OF = {"oneOf": [STRING, {**STRING, "maxLength": 3}]}
ANY_OF = {"anyOf": [STRING, {**STRING, "maxLength": 3}]}


@pytest.mark.parametrize(("mode", "expected"), [("input", MAJOR), ("output", MINOR)])
def test_switching_to_or_from_one_of_is_not_interpreted(mode, expected):
    # oneOf rejects "ab", which both alternatives accept; anyOf accepts it.
    assert details(ANY_OF, ONE_OF, mode) == [(expected, "s", "union keyword anyOf -> oneOf")]
    assert details(ONE_OF, ANY_OF, mode) == [(expected, "s", "union keyword oneOf -> anyOf")]
    integers = {"oneOf": [INTEGER, NUMBER]}
    assert (expected, "s", "union keyword none -> oneOf") in details(
        {"type": ["integer", "number"]}, integers, mode
    )


def test_a_second_union_beside_the_first_is_compared_conservatively():
    old = {**ANY_OF, "oneOf": [STRING]}
    assert details(old, {**ANY_OF, "oneOf": [INTEGER]}) == [
        (MAJOR, "s", 'oneOf [{"type":"string"}] -> [{"type":"integer"}]')
    ]


@pytest.mark.parametrize(("mode", "expected"), [("input", MAJOR), ("output", MINOR)])
def test_a_union_nested_in_a_union_member_is_compared_conservatively(mode, expected):
    old = nullable({"anyOf": [STRING, INTEGER]})
    assert level(old, nullable({"anyOf": [STRING]}), mode) is expected
