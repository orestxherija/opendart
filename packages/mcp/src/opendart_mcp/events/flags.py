"""Red flags and notable features read from event reports.

Yes/no columns keep one meaning across services (``bdlst_atn`` is always "deemed a backdoor
listing"), so one table maps them to flag names. A few flags come from free text, such as a
private placement in the bond issuance method. The service adds ``amended`` when the filing
index shows the row reflects a corrected filing, and ``possibly_amended`` when, without an
index title, a major-issue decision's latest filing came well after its board date.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_mcp.events.values import parse_flag

if TYPE_CHECKING:
    from collections.abc import Mapping

    from opendart_mcp.events.records import EventRecord

AMENDED: Final = "amended"
"""Flag for events whose row reflects a corrected filing."""
POSSIBLY_AMENDED: Final = "possibly_amended"
"""Flag for decisions whose latest filing came well after the board date, which usually
means a correction that the filing index could not confirm."""

FLAG_FIELDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bdlst_atn": "backdoor_listing",
        "otcpr_bdlst_sf_atn": "backdoor_listing_criteria_met",
        "iscmp_bdlst_sf_atn": "backdoor_listing_criteria_met",
        "n6m_tpai_plann": "third_party_allotment_planned",
        "l6m_tpa_nstkaq_atn": "recent_third_party_allotment",
        "popt_ctr_atn": "put_option",
        "ftc_stt_atn": "ftc_reporting",
        "ssl_at": "short_sale_restriction",
        "gmtsck_spd_atn": "special_resolution",
        "nmgcmp_rlst_atn": "relisting_planned",
        "dvfcmp_rlst_atn": "relisting_planned",
        "bdwt_div_atn": "detachable_warrants",
        "absn_inh_atn": "whole_business",
    }
)
"""Yes/no field to the flag raised when the field says yes."""

_THIRD_PARTY: Final = ("third-party", "third party", "제3자")
_TEXT_FLAGS: Final[tuple[tuple[str, tuple[str, ...], str], ...]] = (
    ("bdis_mthn", ("private", "사모"), "private_placement"),
    ("ic_mthn", _THIRD_PARTY, "third_party_allotment"),
    ("piic_ic_mthn", _THIRD_PARTY, "third_party_allotment"),
)


def event_flags(record: EventRecord) -> tuple[str, ...]:
    """List the flags an event report raises, in table order.

    Args:
        record (EventRecord): Event rows.

    Returns:
        tuple[str, ...]: Flag names without duplicates.
    """
    flags = dict.fromkeys(
        flag for name, flag in FLAG_FIELDS.items() if parse_flag(record.raw(name))
    )
    for name, words, flag in _TEXT_FLAGS:
        text = (record.raw(name) or "").casefold()
        if any(word in text for word in words):
            flags.setdefault(flag)
    return tuple(flags)
