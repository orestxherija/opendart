"""Event vocabulary: kinds and groups match the design, services, and date fields."""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from opendart_mcp.registry import (
    EVENT_GROUPS,
    EVENT_KINDS,
    EVENT_KIND_NAMES,
    EventGroup,
    EventKind,
    expand,
    kinds_in,
    service,
    services,
)

DESIGN = Path(__file__).resolve().parents[2] / "docs/COMPONENT_DESIGN.md"


def design_vocabulary() -> list[tuple[str, str, str]]:
    """Parse the get_corporate_events vocabulary table: (kind, group, SDK method).

    Its rows are the only ones whose first cell is one code word and whose second cell lists
    kinds as `kind` (`method`).
    """
    text = DESIGN.read_text(encoding="utf-8")
    rows = re.findall(r"^\| `(\w+)` \| (`\w+` \(`\w+`\).*) \|$", text, re.MULTILINE)
    return [
        (kind, group, method)
        for group, kinds in rows
        for kind, method in re.findall(r"`(\w+)` \(`(\w+)`\)", kinds)
    ]


def test_vocabulary_matches_the_design_table():
    expected = design_vocabulary()
    assert len(expected) == 42, f"Vocabulary table not found or changed in {DESIGN}"
    assert [(spec.kind, spec.group, spec.service) for spec in EVENT_KINDS.values()] == expected
    assert tuple(dict.fromkeys(group for _, group, _ in expected)) == EVENT_GROUPS


def test_literals_list_every_kind_and_group_in_order():
    assert typing.get_args(EventKind) == EVENT_KIND_NAMES == tuple(EVENT_KINDS)
    assert typing.get_args(EventGroup) == EVENT_GROUPS
    assert len(EVENT_GROUPS) == 8
    assert all(spec.kind == kind for kind, spec in EVENT_KINDS.items())


def test_every_event_service_is_covered_exactly_once():
    event_services = [spec.service for spec in EVENT_KINDS.values()]
    assert len(event_services) == len(set(event_services)) == 42
    upstream = {
        spec.name for spec in services("major_issues") + services("securities_registration")
    }
    assert set(event_services) == upstream
    for spec in EVENT_KINDS.values():
        registered = service(spec.service)
        assert spec.resource == registered.resource
        assert spec.title == registered.title


@pytest.mark.parametrize("kind", EVENT_KIND_NAMES)
def test_date_fields_are_the_date_and_period_fields(kind):
    spec = EVENT_KINDS[kind]
    expected = {}
    for field in service(spec.service).fields:
        if field.kind in {"date", "period"}:
            expected.setdefault(field.name, field.label)
    assert spec.date_fields == tuple(expected.items())
    names = [name for name, _ in spec.date_fields]
    assert len(names) == len(set(names))


def test_date_fields_for_representative_kinds():
    convertible = dict(EVENT_KINDS["convertible_bond"].date_fields)
    assert convertible["cvrqpd_bgd"] == "Terms of conversion(Conversion request period(Start date))"
    assert {"bd_mtd", "cvrqpd_edd", "sbd", "pymd", "bddd"} <= set(convertible)
    offering = dict(EVENT_KINDS["equity_offering_registration"].date_fields)
    assert list(offering)[:5] == ["sbd", "pymd", "sband", "asand", "asstd"]
    # The redemption-claim section reuses expd; the first section's label is kept.
    assert offering["expd"] == "Details of warrants (exercise period)"
    trust = dict(EVENT_KINDS["treasury_trust_contract"].date_fields)
    assert trust["ctr_pd_edd"] == "Contract period(End date)"
    assert EVENT_KINDS["asset_deal_put_back_option"].date_fields == ()


def test_kinds_in_groups():
    assert kinds_in("buyback") == (
        "treasury_stock_acquisition",
        "treasury_stock_disposal",
        "treasury_trust_contract",
        "treasury_trust_termination",
    )
    assert kinds_in("capital_reduction") == ("capital_reduction",)
    assert sum(len(kinds_in(group)) for group in EVENT_GROUPS) == 42
    with pytest.raises(
        ValueError, match="Unknown event group 'convertible_bond'; groups: capital_raise"
    ):
        kinds_in("convertible_bond")


def test_expand_mixes_groups_and_kinds_without_duplicates():
    assert expand(["convertible_bond", "buyback", "treasury_stock_acquisition"]) == (
        "convertible_bond",
        "treasury_stock_acquisition",
        "treasury_stock_disposal",
        "treasury_trust_contract",
        "treasury_trust_termination",
    )
    assert expand(["lawsuit", "merger"]) == ("merger", "lawsuit")
    assert expand([]) == ()
    assert expand(EVENT_GROUPS) == EVENT_KIND_NAMES


def test_expand_prefers_groups_for_shared_names():
    assert expand(["overseas_listing"]) == kinds_in("overseas_listing")
    assert len(expand("overseas_listing")) == 4
    assert expand("capital_reduction") == ("capital_reduction",)


def test_only_capital_reduction_names_both_a_group_and_a_kind():
    assert set(EVENT_GROUPS) & set(EVENT_KIND_NAMES) == {"capital_reduction"}
    assert expand("overseas_listing_completed") == ("overseas_listing_completed",)
    assert EVENT_KINDS["overseas_listing_completed"].service == "ov_lst"


def test_expand_rejects_unknown_names_with_the_valid_ones():
    with pytest.raises(ValueError, match=r"Unknown event categories: cb, dividend\.") as error:
        expand(["cb", "convertible_bond", "dividend"])
    assert "Kinds: rights_or_third_party_issue" in str(error.value)
    assert "overseas_delisting." in str(error.value)
