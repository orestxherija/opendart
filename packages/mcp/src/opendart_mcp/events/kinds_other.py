"""Presentations for distress and legal events and for overseas listings.

Distress reports are mostly free text (causes, courts, next steps), so headlines quote the
first words of the filed text; their dates are facts, not calendar items.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.events.templates import Presentation, part

if TYPE_CHECKING:
    from opendart_mcp.registry import EventKind

OTHER: Final[dict[EventKind, Presentation]] = {
    "default_or_bankruptcy": Presentation(
        label="Default or bankruptcy",
        lead=part("Default: {}", "df_cn"),
        parts=(part("amount {}", "df_amt"), part("bank {}", "df_bnk"), part("reason: {}", "df_rs")),
        terms=(("details", "df_cn"), ("amount", "df_amt"), ("bank", "df_bnk"), ("reason", "df_rs")),
    ),
    "rehabilitation_filing": Presentation(
        label="Rehabilitation filing",
        lead=part("Rehabilitation filing by {}", "apcnt"),
        parts=(part("court {}", "cpct"), part("reason: {}", "rq_rs")),
        terms=(
            ("applicant", "apcnt"),
            ("court", "cpct"),
            ("reason", "rq_rs"),
            ("next_steps", "ft_ctp_sc"),
        ),
    ),
    "creditor_workout_start": Presentation(
        label="Creditor-bank management",
        lead=part("Creditor-bank management by {}", "mngt_int"),
        parts=(part("period {}", "mngt_pd"), part("cause: {}", "mngt_rs")),
        terms=(("institution", "mngt_int"), ("period", "mngt_pd"), ("cause", "mngt_rs")),
    ),
    "creditor_workout_suspension": Presentation(
        label="Creditor-bank management suspended",
        lead=part("Creditor-bank management by {} suspended", "mngt_int"),
        parts=(part("cause: {}", "sp_rs"), part("next: {}", "ft_ctp")),
        terms=(("institution", "mngt_int"), ("cause", "sp_rs"), ("next_steps", "ft_ctp")),
    ),
    "dissolution_cause": Presentation(
        label="Dissolution cause",
        lead=part("Dissolution cause: {}", "ds_rs"),
        terms=(("cause", "ds_rs"),),
    ),
    "business_suspension": Presentation(
        label="Business suspension",
        lead=part("Business suspension: {}", "bsnsp_rm"),
        parts=(
            part("{} of sales", "bsnsp_amt"),
            part("{} of total sales", "sl_vs"),
            part("reason: {}", "bsnsp_rs"),
        ),
        terms=(
            ("business", "bsnsp_rm"),
            ("sales_suspended", "bsnsp_amt"),
            ("sales_pct", "sl_vs"),
            ("reason", "bsnsp_rs"),
            ("next_steps", "ft_ctp"),
        ),
    ),
    "lawsuit": Presentation(
        label="Lawsuit",
        lead=part("Lawsuit: {}", "icnm"),
        parts=(part("plaintiff {}", "ac_ap"), part("court {}", "cpct"), part("claim: {}", "rq_cn")),
        terms=(
            ("case", "icnm"),
            ("plaintiff", "ac_ap"),
            ("court", "cpct"),
            ("claim", "rq_cn"),
            ("next_steps", "ft_ctp"),
        ),
    ),
    "overseas_listing_decision": Presentation(
        label="Overseas listing decision",
        lead=part("Overseas listing decided on {}", "lstex_nt"),
        parts=(
            part("{} common shares", "lstprstk_ostk_cnt"),
            part("{} new shares offered", "psmth_nstk_sl"),
            part("purpose: {}", "lstpp"),
        ),
        terms=(
            ("exchange", "lstex_nt"),
            ("shares", "lstprstk_ostk_cnt"),
            ("other_shares", "lstprstk_estk_cnt"),
            ("new_shares_offered", "psmth_nstk_sl"),
            ("shares_sold", "psmth_ostk_sl"),
            ("purpose", "lstpp"),
        ),
    ),
    "overseas_listing_completed": Presentation(
        label="Overseas listing",
        lead=part("Listed overseas on {}", "lstex_nt"),
        parts=(part("{} common shares", "lststk_ostk_cnt"), part("code {}", "stk_cd")),
        terms=(
            ("exchange", "lstex_nt"),
            ("shares", "lststk_ostk_cnt"),
            ("other_shares", "lststk_estk_cnt"),
            ("code", "stk_cd"),
        ),
    ),
    "overseas_delisting_decision": Presentation(
        label="Overseas delisting decision",
        lead=part("Overseas delisting decided on {}", "lstex_nt"),
        parts=(part("{} common shares", "dlststk_ostk_cnt"), part("reason: {}", "dlst_rs")),
        terms=(
            ("exchange", "lstex_nt"),
            ("shares", "dlststk_ostk_cnt"),
            ("other_shares", "dlststk_estk_cnt"),
            ("reason", "dlst_rs"),
        ),
    ),
    "overseas_delisting": Presentation(
        label="Overseas delisting",
        lead=part("Delisted overseas from {}", "lstex_nt"),
        parts=(part("{} common shares", "dlststk_ostk_cnt"), part("reason: {}", "dlst_rs")),
        terms=(
            ("exchange", "lstex_nt"),
            ("shares", "dlststk_ostk_cnt"),
            ("other_shares", "dlststk_estk_cnt"),
            ("reason", "dlst_rs"),
        ),
    ),
}
"""Presentations of the distress_and_legal and overseas_listing kinds."""
