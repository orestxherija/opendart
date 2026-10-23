"""The vocabulary, filing-category, and event-kind reference resources."""

from __future__ import annotations

import json
from typing import get_args

import pytest

from opendart_mcp.domain.categories import CATEGORY_INFO, FILING_CATEGORIES
from opendart_mcp.domain.types import Basis, Market, MarketFilter, Period, ResponseFormat, Unit
from opendart_mcp.events import CALENDAR_KINDS, PRESENTATIONS
from opendart_mcp.registry import EVENT_GROUPS, EVENT_KINDS
from opendart_mcp.resources.reference import (
    BASIS_MEANINGS,
    FORMAT_MEANINGS,
    GROUP_MEANINGS,
    UNIT_MEANINGS,
)

VOCABULARY = "opendart://reference/vocabulary"
CATEGORIES = "opendart://reference/filing-categories"
EVENTS = "opendart://reference/event-kinds"


async def read(client, uri):
    (content,) = await client.read_resource(uri)
    return content


@pytest.mark.anyio
async def test_reference_resources_are_listed_for_the_assistant(client):
    resources = {str(r.uri): r for r in await client.list_resources()}
    expected = {VOCABULARY: "text/markdown", CATEGORIES: "application/json"}
    expected[EVENTS] = "application/json"
    for uri, mime in expected.items():
        resource = resources[uri]
        assert resource.mime_type == mime
        assert resource.title
        assert resource.description
        assert resource.meta is not None
        assert resource.meta["fastmcp"]["version"] == "1.0.0"
        assert resource.annotations is not None
        assert resource.annotations.audience == ["assistant"]


def test_meaning_tables_cover_their_vocabularies_exactly():
    assert tuple(BASIS_MEANINGS) == get_args(Basis)
    assert tuple(UNIT_MEANINGS) == get_args(Unit)
    assert tuple(FORMAT_MEANINGS) == get_args(ResponseFormat)
    assert tuple(GROUP_MEANINGS) == EVENT_GROUPS


@pytest.mark.anyio
async def test_the_vocabulary_documents_every_accepted_value(client, upstream):
    content = await read(client, VOCABULARY)
    assert content.mime_type == "text/markdown"
    text = content.text
    vocabularies = (Period, Basis, Unit, Market, MarketFilter, ResponseFormat)
    for value in (v for vocabulary in vocabularies for v in get_args(vocabulary)):
        assert f"`{value}`" in text
    for name in (*FILING_CATEGORIES, *EVENT_GROUPS):
        assert f"`{name}`" in text
    assert "| `FY` | annual | 11011 | 90 days |" in text
    assert "Data starts with fiscal 2015; financial ratios with 2022." in text
    assert "No prices, volumes, market capitalization" in text
    assert "annual reports are due 90 days" in text
    assert "00:00 KST" in text
    assert upstream.count("/company.json") == 0


@pytest.mark.anyio
async def test_filing_categories_map_names_to_upstream_codes(client):
    content = await read(client, CATEGORIES)
    assert content.mime_type == "application/json"
    data = json.loads(content.text)
    entries = data["categories"]
    assert [entry["name"] for entry in entries] == list(FILING_CATEGORIES)
    by_name = {entry["name"]: entry for entry in entries}
    assert by_name["annual_report"] == {
        "name": "annual_report",
        "pblntf_ty": "A",
        "pblntf_detail_ty": "A001",
        "description": CATEGORY_INFO["annual_report"].description,
    }
    assert by_name["major_issues"]["pblntf_detail_ty"] is None
    assert "search_filings" in data["usage"]


@pytest.mark.anyio
async def test_event_kinds_follow_the_registry(client):
    data = json.loads((await read(client, EVENTS)).text)
    assert [group["group"] for group in data["groups"]] == list(EVENT_GROUPS)
    kinds = {kind["kind"]: kind for group in data["groups"] for kind in group["kinds"]}
    assert list(kinds) == list(EVENT_KINDS)
    bond = kinds["convertible_bond"]
    spec = EVENT_KINDS["convertible_bond"]
    assert (bond["service"], bond["resource"], bond["title"]) == (
        spec.service,
        spec.resource,
        spec.title,
    )
    assert bond["date_fields"] == dict(spec.date_fields)
    assert "sbd" in bond["date_fields"]
    assert bond["label"] == PRESENTATIONS["convertible_bond"].label
    assert bond["key_terms"] == [key for key, _ in PRESENTATIONS["convertible_bond"].terms]
    assert "conversion_price" in bond["key_terms"]
    assert {kind for kind, entry in kinds.items() if entry["calendar"]} == set(CALENDAR_KINDS)
    assert all(group["description"] for group in data["groups"])
    assert "get_corporate_events" in data["usage"]
