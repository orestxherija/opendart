"""Schedule dates in event reports: which fields hold them and what each date means.

Field names keep one meaning across services (``sbd`` is always the subscription date, the
``mgsc_``, ``dvmgsc_``, and ``extrsc_`` prefixes are merger, split-merger, and share-swap
schedules), so one table maps fields to action codes such as ``record_date`` or
``conversion_start``. Board resolution dates feed ``board_date`` instead, and a few fields
are not schedule dates at all (external valuation periods, financial statement dates).
A date range in a single field (``2026.12.14 ~ 2026.12.15``) becomes ``*_start`` and
``*_end`` actions. Facts such as a lawsuit's filing date, or the contract period a trust
termination cuts short, are kept for events but never appear in the forward calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_mcp.events.values import parse_span
from opendart_mcp.registry import EVENT_KINDS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from opendart_mcp.events.records import EventRecord
    from opendart_mcp.registry import EventKind, EventKindSpec


@dataclass(frozen=True, slots=True)
class Action:
    """What a date means.

    Attributes:
        code (str): Action code used in results, such as record_date.
        label (str): Short English label for Markdown.
        calendar (bool): Whether the date belongs in the corporate-action calendar; facts
            such as a lawsuit's filing date do not.
    """

    code: str
    label: str
    calendar: bool


_SCHEDULE: Final[tuple[tuple[str, str], ...]] = (
    ("subscription", "Subscription"),
    ("subscription_start", "Subscription starts"),
    ("subscription_end", "Subscription ends"),
    ("subscription_announcement", "Subscription announcement"),
    ("allotment_announcement", "Allotment announcement"),
    ("payment_date", "Payment date"),
    ("record_date", "Record date"),
    ("dividend_base_date", "Dividend base date of new shares"),
    ("certificate_delivery", "New share certificates delivered"),
    ("listing_date", "Listing date"),
    ("short_sale_ban_start", "Short-sale restriction starts"),
    ("short_sale_ban_end", "Short-sale restriction ends"),
    ("maturity", "Maturity"),
    ("conversion_start", "Conversion period opens"),
    ("conversion_end", "Conversion period ends"),
    ("exercise", "Exercise period"),
    ("exercise_start", "Exercise period opens"),
    ("exercise_end", "Exercise period ends"),
    ("exchange_start", "Exchange period opens"),
    ("exchange_end", "Exchange period ends"),
    ("redemption_claim", "Subscriber put-back period"),
    ("redemption_claim_start", "Subscriber put-back period opens"),
    ("redemption_claim_end", "Subscriber put-back period ends"),
    ("buyback_start", "Buyback period starts"),
    ("buyback_end", "Buyback period ends"),
    ("holding_start", "Holding period starts"),
    ("holding_end", "Holding period ends"),
    ("disposal_start", "Disposal period starts"),
    ("disposal_end", "Disposal period ends"),
    ("trust_start", "Trust contract starts"),
    ("trust_end", "Trust contract ends"),
    ("termination_date", "Trust termination"),
    ("contract_date", "Contract date"),
    ("shareholder_meeting", "Shareholders' meeting"),
    ("book_closure", "Book closure"),
    ("book_closure_start", "Book closure starts"),
    ("book_closure_end", "Book closure ends"),
    ("objection_start", "Dissent notice period opens"),
    ("objection_end", "Dissent notice period ends"),
    ("appraisal_start", "Appraisal rights period opens"),
    ("appraisal_end", "Appraisal rights period ends"),
    ("certificate_submission", "Old certificate submission"),
    ("certificate_submission_start", "Old certificate submission starts"),
    ("certificate_submission_end", "Old certificate submission ends"),
    ("suspension", "Trading suspension"),
    ("suspension_start", "Trading suspension starts"),
    ("suspension_end", "Trading suspension ends"),
    ("creditor_objection_start", "Creditor objection period opens"),
    ("creditor_objection_end", "Creditor objection period ends"),
    ("effective_date", "Effective date"),
    ("completion_meeting", "Completion report meeting"),
    ("registration_date", "Registration date"),
    ("closing_date", "Closing date"),
    ("management_period", "Creditor management period"),
    ("management_period_start", "Creditor management starts"),
    ("management_period_end", "Creditor management ends"),
    ("suspension_effective", "Business suspension takes effect"),
    ("delisting_application", "Delisting application"),
    ("delisting_date", "Delisting date"),
    ("last_trading_day", "Last trading day"),
)
_FACTS: Final[tuple[tuple[str, str], ...]] = (
    ("default_date", "Default occurred"),
    ("application_date", "Rehabilitation applied for"),
    ("workout_decided", "Creditor management decided"),
    ("workout_suspended", "Creditor management suspended"),
    ("dissolution_cause_date", "Dissolution cause arose"),
    ("lawsuit_filed", "Lawsuit filed"),
    ("confirmed", "Confirmed by the company"),
    ("terminated_trust_start", "Terminated trust contract started"),
    ("terminated_trust_end", "Terminated trust contract was due to end"),
)
ACTIONS: Final[Mapping[str, Action]] = MappingProxyType(
    {
        **{code: Action(code, label, calendar=True) for code, label in _SCHEDULE},
        **{code: Action(code, label, calendar=False) for code, label in _FACTS},
    }
)
"""Every action code in display order."""
_ORDER: Final = {code: index for index, code in enumerate(ACTIONS)}

BOARD_DATE_FIELDS: Final = ("bddd", "aq_dd", "dp_dd", "fric_bddd")
"""Board resolution (decision) date fields, in order of preference."""
IGNORED_DATE_FIELDS: Final = frozenset({"exevl_pd", "ffdtl_std", "atdvfdtl_std", "aqd"})
"""Date fields that are not schedule dates: valuation periods, statement dates, and the
date bonds being sold were originally acquired."""


def _same(action: str, *names: str) -> dict[str, str]:
    """Map several field names to one action.

    Args:
        action (str): Action code.
        *names (str): SDK field names.

    Returns:
        dict[str, str]: Field name to action code.
    """
    return dict.fromkeys(names, action)


def _schedule(prefixes: tuple[str, ...], suffix: str, action: str) -> dict[str, str]:
    """Map a schedule field shared by several prefixes (mgsc_, dvmgsc_, extrsc_).

    Args:
        prefixes (tuple[str, ...]): Field name prefixes.
        suffix (str): Field name after the prefix.
        action (str): Action code.

    Returns:
        dict[str, str]: Field name to action code.
    """
    return {f"{prefix}{suffix}": action for prefix in prefixes}


_DEALS: Final = ("mgsc_", "dvmgsc_", "extrsc_")
DATE_FIELDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "sbd": "subscription",
        "pymd": "payment_date",
        "sband": "subscription_announcement",
        "asand": "allotment_announcement",
        **_same("record_date", "asstd", "nstk_asstd", "fric_nstk_asstd", "abcr_nstkasstd"),
        **_same("record_date", "cr_std", "gmtsck_shddstd", *(f"{p}shddstd" for p in _DEALS)),
        **_same("dividend_base_date", "nstk_dividrk", "fric_nstk_dividrk"),
        **_same("certificate_delivery", "nstk_dlprd", "fric_nstk_dlprd", "crsc_nstkdlprd"),
        **_same("certificate_delivery", "abcr_nstkdlprd", "mgsc_nstkdlprd", "extrsc_nstkdlprd"),
        **_same("listing_date", "nstk_lstprd", "fric_nstk_lstprd", "crsc_nstklstprd", "lstprd"),
        **_same("listing_date", "abcr_nstklstprd", "mgsc_nstklstprd", "extrsc_nstklstprd", "lstd"),
        "ssl_bgd": "short_sale_ban_start",
        "ssl_edd": "short_sale_ban_end",
        **_same("maturity", "bd_mtd", "rpd", "drcb_mtd"),
        "cvrqpd_bgd": "conversion_start",
        "cvrqpd_edd": "conversion_end",
        **_same("exercise", "expd", "estk_expd"),
        "expd_bgd": "exercise_start",
        "expd_edd": "exercise_end",
        "exrqpd_bgd": "exchange_start",
        "exrqpd_edd": "exchange_end",
        "aqexpd_bgd": "buyback_start",
        "aqexpd_edd": "buyback_end",
        "hdexpd_bgd": "holding_start",
        "hdexpd_edd": "holding_end",
        "dpprpd_bgd": "disposal_start",
        "dpprpd_edd": "disposal_end",
        "ctr_pd_bgd": "trust_start",
        "ctr_pd_edd": "trust_end",
        # A termination report restates the contract period it cuts short: facts, not dates
        # still ahead.
        "ctr_pd_bfcc_bgd": "terminated_trust_start",
        "ctr_pd_bfcc_edd": "terminated_trust_end",
        "cc_prd": "termination_date",
        **_same("contract_date", "ctr_cns_prd", "ctrd", "inh_prd_ctr_cnsd", "trf_prd_ctr_cnsd"),
        **_same("contract_date", "mgsc_mgctrd", "dvmgsc_dvmgctrd", "extrsc_extrctrd"),
        **_same("shareholder_meeting", "crsc_gmtsck_prd", "gmtsck_prd", "ap_gmtsck"),
        **_schedule(_DEALS, "gmtsck_prd", "shareholder_meeting"),
        "crsc_trnmsppd": "book_closure",
        **_schedule(_DEALS, "shclspd_bgd", "book_closure_start"),
        **_schedule(_DEALS, "shclspd_edd", "book_closure_end"),
        **_same("objection_start", "mgsc_mgop_rcpd_bgd", "dvmgsc_dvmgop_rcpd_bgd"),
        **_same("objection_start", "extrsc_extrop_rcpd_bgd"),
        **_same("objection_end", "mgsc_mgop_rcpd_edd", "dvmgsc_dvmgop_rcpd_edd"),
        **_same("objection_end", "extrsc_extrop_rcpd_edd"),
        **_same("appraisal_start", "aprskh_pd_bgd", *(f"{p}aprskh_expd_bgd" for p in _DEALS)),
        **_same("appraisal_end", "aprskh_pd_edd", *(f"{p}aprskh_expd_edd" for p in _DEALS)),
        "crsc_osprpd": "certificate_submission",
        **_same("certificate_submission_start", "crsc_osprpd_bgd", "abcr_osprpd_bgd"),
        **_same("certificate_submission_start", "mgsc_osprpd_bgd", "extrsc_osprpd_bgd"),
        **_same("certificate_submission_end", "crsc_osprpd_edd", "abcr_osprpd_edd"),
        **_same("certificate_submission_end", "mgsc_osprpd_edd", "extrsc_osprpd_edd"),
        **_same("suspension", "crsc_trspprpd", "extrsc_trspprpd"),
        **_same("suspension_start", "crsc_trspprpd_bgd", "abcr_trspprpd_bgd"),
        **_same("suspension_start", "mgsc_trspprpd_bgd", "extrsc_trspprpd_bgd"),
        **_same("suspension_end", "crsc_trspprpd_edd", "abcr_trspprpd_edd"),
        **_same("suspension_end", "mgsc_trspprpd_edd", "extrsc_trspprpd_edd"),
        **_same("creditor_objection_start", "cdobprpd_bgd", "mgsc_cdobprpd_bgd"),
        **_same("creditor_objection_start", "dvmgsc_cdobprpd_bgd"),
        **_same("creditor_objection_end", "cdobprpd_edd", "mgsc_cdobprpd_edd"),
        **_same("creditor_objection_end", "dvmgsc_cdobprpd_edd"),
        **_same("effective_date", "mgsc_mgdt", "dvmgsc_dvmgdt", "extrsc_extrdt", "dvdt"),
        "mgdt_etc": "effective_date",
        **_same("completion_meeting", "mgsc_ergmd", "dvmgsc_ergmd"),
        **_same("registration_date", "mgsc_mgrgsprd", "dvmgsc_dvmgrgsprd", "dvrgsprd"),
        **_same("registration_date", "inh_prd_rgs_prd", "trf_prd_rgs_prd"),
        **_same("closing_date", "inh_prd_inh_std", "trf_prd_trf_std", "inh_prd", "trf_prd"),
        "mngt_pd": "management_period",
        "bsnspd": "suspension_effective",
        "dlstrq_prd": "delisting_application",
        "dlst_prd": "delisting_date",
        "tredd": "last_trading_day",
        "dfd": "default_date",
        "rqd": "application_date",
        "mngt_pcbg_dd": "workout_decided",
        "mngt_pcsp_dd": "workout_suspended",
        "ds_rsd": "dissolution_cause_date",
        "lgd": "lawsuit_filed",
        "cfd": "confirmed",
    }
)
"""SDK field name to action code for every schedule and fact date field."""

# The equity registration statement reuses expd for the subscriber put-back right.
_SECTION_OVERRIDES: Final = (("redemption", "expd", "redemption_claim"),)
_RANGED: Final = frozenset(
    code for code in ACTIONS if f"{code}_start" in ACTIONS and f"{code}_end" in ACTIONS
)


def _action(section: str, name: str) -> str | None:
    """Find the action of a field, honoring section-specific meanings.

    Args:
        section (str): Catalog section of the row; empty for single-record services.
        name (str): SDK field name.

    Returns:
        str | None: Action code, or None when the field is not a date field.
    """
    lowered = section.casefold()
    for marker, field, action in _SECTION_OVERRIDES:
        if field == name and marker in lowered:
            return action
    return DATE_FIELDS.get(name)


def _expand(action: str, span: tuple[date, date] | None) -> tuple[tuple[str, date], ...]:
    """Turn a parsed value into dated actions, splitting ranges.

    Args:
        action (str): Action code of the field.
        span (tuple[date, date] | None): Parsed date or range.

    Returns:
        tuple[tuple[str, date], ...]: (action, date) pairs.
    """
    if span is None:
        return ()
    start, end = span
    if start != end and action in _RANGED:
        return ((f"{action}_start", start), (f"{action}_end", end))
    return ((action, start),)


def event_dates(record: EventRecord) -> tuple[tuple[str, date], ...]:
    """List an event's dated actions in date order, without duplicates.

    Args:
        record (EventRecord): Event rows.

    Returns:
        tuple[tuple[str, date], ...]: (action code, date) pairs.
    """
    found: dict[tuple[str, date], None] = {}
    for row in record.rows:
        for name, raw in row.values.items():
            action = _action(row.section, name)
            if action is not None:
                found.update(dict.fromkeys(_expand(action, parse_span(raw))))
    return tuple(sorted(found, key=lambda pair: (pair[1], _ORDER[pair[0]])))


def board_date(record: EventRecord) -> date | None:
    """Return the board resolution (decision) date, when the report has one.

    Args:
        record (EventRecord): Event rows.

    Returns:
        date | None: First day of the first readable board date field.
    """
    for name in BOARD_DATE_FIELDS:
        span = parse_span(record.raw(name))
        if span is not None:
            return span[0]
    return None


def _has_calendar_dates(spec: EventKindSpec) -> bool:
    """Check whether a kind's report has any forward-looking schedule date.

    Args:
        spec (EventKindSpec): Event kind.

    Returns:
        bool: True when a date field maps to a calendar action.
    """
    actions = (DATE_FIELDS.get(name) for name, _ in spec.date_fields)
    return any(ACTIONS[action].calendar for action in actions if action is not None)


CALENDAR_KINDS: Final[frozenset[EventKind]] = frozenset(
    kind for kind, spec in EVENT_KINDS.items() if _has_calendar_dates(spec)
)
"""Kinds whose reports carry dates for the corporate-action calendar."""
