"""Event vocabulary for get_corporate_events: groups, kinds, upstream services, and date fields.

Each of the 42 event kinds maps to one major-issue report or securities-registration service.
The kind, its group, and its service are reviewed here; the resource, title, and date fields
come from the generated registry, so they follow the catalog.

Per-kind presentation (headline templates, key-term selections, and flags) belongs in a
separate module keyed by EventKind, such as a Mapping[EventKind, Template]; a test comparing its
keys with EVENT_KINDS keeps the two in step when kinds are added.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, get_args

from opendart_mcp.registry.catalog import service

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from opendart_mcp.registry.specs import Resource

# Plain aliases rather than type statements, so typing.get_args() lists the values at runtime.
EventGroup = Literal[
    "capital_raise",
    "convertible_and_hybrid_debt",
    "buyback",
    "capital_reduction",
    "mna_and_restructuring",
    "asset_and_investment_deals",
    "distress_and_legal",
    "overseas_listing",
]
EventKind = Literal[
    "rights_or_third_party_issue",
    "bonus_issue",
    "combined_paid_and_bonus_issue",
    "equity_offering_registration",
    "depositary_receipt_registration",
    "convertible_bond",
    "bond_with_warrants",
    "exchangeable_bond",
    "contingent_capital_bond",
    "debt_offering_registration",
    "treasury_stock_acquisition",
    "treasury_stock_disposal",
    "treasury_trust_contract",
    "treasury_trust_termination",
    "capital_reduction",
    "merger",
    "split_off",
    "split_merger",
    "share_swap_or_transfer",
    "business_acquisition",
    "business_transfer",
    "merger_registration",
    "share_swap_registration",
    "split_registration",
    "acquire_other_company_shares",
    "transfer_other_company_shares",
    "acquire_equity_linked_bonds",
    "transfer_equity_linked_bonds",
    "acquire_tangible_assets",
    "transfer_tangible_assets",
    "asset_deal_put_back_option",
    "default_or_bankruptcy",
    "rehabilitation_filing",
    "creditor_workout_start",
    "creditor_workout_suspension",
    "dissolution_cause",
    "business_suspension",
    "lawsuit",
    "overseas_listing_decision",
    "overseas_listing_completed",
    "overseas_delisting_decision",
    "overseas_delisting",
]

EVENT_GROUPS: Final[tuple[EventGroup, ...]] = get_args(EventGroup)
EVENT_KIND_NAMES: Final[tuple[EventKind, ...]] = get_args(EventKind)

# Kind -> (group, SDK method), in the order of the component design's vocabulary table.
_VOCABULARY: Final[dict[EventKind, tuple[EventGroup, str]]] = {
    "rights_or_third_party_issue": ("capital_raise", "piic_decsn"),
    "bonus_issue": ("capital_raise", "fric_decsn"),
    "combined_paid_and_bonus_issue": ("capital_raise", "pifric_decsn"),
    "equity_offering_registration": ("capital_raise", "estk_rs"),
    "depositary_receipt_registration": ("capital_raise", "stkdp_rs"),
    "convertible_bond": ("convertible_and_hybrid_debt", "cvbd_is_decsn"),
    "bond_with_warrants": ("convertible_and_hybrid_debt", "bdwt_is_decsn"),
    "exchangeable_bond": ("convertible_and_hybrid_debt", "exbd_is_decsn"),
    "contingent_capital_bond": ("convertible_and_hybrid_debt", "wd_cocobd_is_decsn"),
    "debt_offering_registration": ("convertible_and_hybrid_debt", "bd_rs"),
    "treasury_stock_acquisition": ("buyback", "tsstk_aq_decsn"),
    "treasury_stock_disposal": ("buyback", "tsstk_dp_decsn"),
    "treasury_trust_contract": ("buyback", "tsstk_aq_trctr_cns_decsn"),
    "treasury_trust_termination": ("buyback", "tsstk_aq_trctr_cc_decsn"),
    "capital_reduction": ("capital_reduction", "cr_decsn"),
    "merger": ("mna_and_restructuring", "cmp_mg_decsn"),
    "split_off": ("mna_and_restructuring", "cmp_dv_decsn"),
    "split_merger": ("mna_and_restructuring", "cmp_dvmg_decsn"),
    "share_swap_or_transfer": ("mna_and_restructuring", "stk_extr_decsn"),
    "business_acquisition": ("mna_and_restructuring", "bsn_inh_decsn"),
    "business_transfer": ("mna_and_restructuring", "bsn_trf_decsn"),
    "merger_registration": ("mna_and_restructuring", "mg_rs"),
    "share_swap_registration": ("mna_and_restructuring", "extr_rs"),
    "split_registration": ("mna_and_restructuring", "dv_rs"),
    "acquire_other_company_shares": ("asset_and_investment_deals", "otcpr_stk_invscr_inh_decsn"),
    "transfer_other_company_shares": ("asset_and_investment_deals", "otcpr_stk_invscr_trf_decsn"),
    "acquire_equity_linked_bonds": ("asset_and_investment_deals", "stkrtbd_inh_decsn"),
    "transfer_equity_linked_bonds": ("asset_and_investment_deals", "stkrtbd_trf_decsn"),
    "acquire_tangible_assets": ("asset_and_investment_deals", "tgast_inh_decsn"),
    "transfer_tangible_assets": ("asset_and_investment_deals", "tgast_trf_decsn"),
    "asset_deal_put_back_option": ("asset_and_investment_deals", "ast_inhtrf_etc_ptbk_opt"),
    "default_or_bankruptcy": ("distress_and_legal", "df_ocr"),
    "rehabilitation_filing": ("distress_and_legal", "ctrcvs_bgrq"),
    "creditor_workout_start": ("distress_and_legal", "bnk_mngt_pcbg"),
    "creditor_workout_suspension": ("distress_and_legal", "bnk_mngt_pcsp"),
    "dissolution_cause": ("distress_and_legal", "ds_rs_ocr"),
    "business_suspension": ("distress_and_legal", "bsn_sp"),
    "lawsuit": ("distress_and_legal", "lwst_lg"),
    "overseas_listing_decision": ("overseas_listing", "ov_lst_decsn"),
    "overseas_listing_completed": ("overseas_listing", "ov_lst"),
    "overseas_delisting_decision": ("overseas_listing", "ov_dlst_decsn"),
    "overseas_delisting": ("overseas_listing", "ov_dlst"),
}


@dataclass(frozen=True, slots=True)
class EventKindSpec:
    """One event kind and the upstream service that reports it.

    Attributes:
        kind (EventKind): Event kind name.
        group (EventGroup): Group the kind belongs to.
        service (str): SDK method name, such as cvbd_is_decsn.
        resource (Resource): SDK resource attribute: major_issues or securities_registration.
        title (str): Catalog title of the service.
        date_fields (tuple[tuple[str, str], ...]): (SDK field name, label) pairs for the
            service's date and period fields in catalog order. Registration statements spread
            records over sections; a field name appears once, with its first section's label,
            and service(spec.service).records has the per-section labels.
    """

    kind: EventKind
    group: EventGroup
    service: str
    resource: Resource
    title: str
    date_fields: tuple[tuple[str, str], ...]


def _kind_spec(kind: EventKind, group: EventGroup, name: str) -> EventKindSpec:
    """Build an EventKindSpec from the registry entry of its service.

    Args:
        kind (EventKind): Event kind name.
        group (EventGroup): Group of the kind.
        name (str): SDK method name.

    Returns:
        EventKindSpec: The kind with resource, title, and date fields filled in.

    Raises:
        KeyError: The service is not in the registry.
    """
    spec = service(name)
    dates: dict[str, str] = {}
    for field in spec.fields:
        if field.kind in {"date", "period"}:
            dates.setdefault(field.name, field.label)
    return EventKindSpec(
        kind=kind,
        group=group,
        service=spec.name,
        resource=spec.resource,
        title=spec.title,
        date_fields=tuple(dates.items()),
    )


EVENT_KINDS: Final[Mapping[EventKind, EventKindSpec]] = MappingProxyType(
    {kind: _kind_spec(kind, group, name) for kind, (group, name) in _VOCABULARY.items()}
)
_GROUP_KINDS: Final[dict[str, tuple[EventKind, ...]]] = {
    group: tuple(kind for kind, spec in EVENT_KINDS.items() if spec.group == group)
    for group in EVENT_GROUPS
}
# capital_reduction names both a group and its only kind; the group entry wins (same kinds).
_CATEGORIES: Final[dict[str, tuple[EventKind, ...]]] = {
    **{kind: (kind,) for kind in EVENT_KINDS},
    **_GROUP_KINDS,
}


def kinds_in(group: str) -> tuple[EventKind, ...]:
    """List the kinds of one group in registry order.

    Args:
        group (str): Event group name.

    Returns:
        tuple[EventKind, ...]: Kinds in the group.

    Raises:
        ValueError: The name is not an event group; the message lists the groups.
    """
    if group not in _GROUP_KINDS:
        message = f"Unknown event group {group!r}; groups: {", ".join(EVENT_GROUPS)}"
        raise ValueError(message)
    return _GROUP_KINDS[group]


def expand(categories: str | Iterable[str]) -> tuple[EventKind, ...]:
    """Expand group and kind names into distinct kinds in registry order.

    capital_reduction is both a group and a kind name; the group holds only that kind, so
    either reading selects the same kind. The kind that reports a completed overseas listing is
    named overseas_listing_completed so that overseas_listing always means the whole group.

    Args:
        categories (str | Iterable[str]): Group or kind names; a single string is one name.

    Returns:
        tuple[EventKind, ...]: Selected kinds without duplicates, in EVENT_KINDS order.

    Raises:
        ValueError: A name is neither a group nor a kind; the message lists valid names.
    """
    names = [categories] if isinstance(categories, str) else list(categories)
    if unknown := [name for name in names if name not in _CATEGORIES]:
        groups, kinds = ", ".join(EVENT_GROUPS), ", ".join(EVENT_KINDS)
        message = (
            f"Unknown event categories: {", ".join(unknown)}. Groups: {groups}. Kinds: {kinds}."
        )
        raise ValueError(message)
    selected = {kind for name in names for kind in _CATEGORIES[name]}
    return tuple(kind for kind in EVENT_KINDS if kind in selected)
