"""Filing-category codes match the SDK's disclosure tables.

The categories live in ``opendart_analysis.domain.categories``, which never imports the SDK;
MCP passes their codes to ``disclosures.search``, so this suite checks them against the
generated request model.
"""

from __future__ import annotations

import types
import typing

from opendart.models.disclosures import ListRequest
from opendart_analysis.domain.categories import CATEGORY_INFO


def sdk_values(field: str) -> set[str]:
    """Allowed values of a ListRequest field, read from the generated SDK model."""
    annotation = ListRequest.model_fields[field].annotation
    if isinstance(annotation, types.UnionType):
        annotation = next(arg for arg in typing.get_args(annotation) if arg is not type(None))
    return set(typing.get_args(annotation))


def test_codes_match_the_sdk_tables():
    groups = sdk_values("disclosure_category")
    subtypes = sdk_values("disclosure_subcategory")
    for info in CATEGORY_INFO.values():
        assert info.group in groups
        assert info.subtype is None or (
            info.subtype in subtypes and info.subtype.startswith(info.group)
        )
        assert info.description.endswith(".")


def test_every_upstream_group_is_covered():
    covered = {info.group for info in CATEGORY_INFO.values() if info.subtype is None}
    assert covered == sdk_values("disclosure_category")
