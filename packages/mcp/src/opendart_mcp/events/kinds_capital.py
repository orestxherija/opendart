"""Presentations for capital raises, equity-linked and hybrid bonds, buybacks, and reductions.

Headlines lead with the size of the deal; key terms keep amounts in won, counts as shares,
and percentages under ``*_pct`` keys. Dates are not repeated here: every schedule field
reaches the event's dates through the date table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.events.templates import Presentation, part, ratio, total

if TYPE_CHECKING:
    from opendart_mcp.registry import EventKind

_FUNDING: Final = ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc")


def _offering(label: str, noun: str) -> Presentation:
    """Present an equity or depositary-receipt registration statement.

    Args:
        label (str): Kind label.
        noun (str): Lead noun, such as "Equity offering".

    Returns:
        Presentation: Shared presentation of the two offering statements.
    """
    return Presentation(
        label=label,
        lead=part(noun + " of {} {}", "stkcnt", "stksen"),
        parts=(
            part("at {}", "slprc"),
            part("total {}", "slta"),
            part("{}", "slmthn"),
            part("underwriter {}", "actnmn"),
        ),
        terms=(
            ("security", "stksen"),
            ("quantity", "stkcnt"),
            ("offer_price", "slprc"),
            ("offer_amount", "slta"),
            ("method", "slmthn"),
            ("underwriter", "actnmn"),
            ("decision_filing", "rpt_rcpn"),
        ),
    )


CAPITAL: Final[dict[EventKind, Presentation]] = {
    "rights_or_third_party_issue": Presentation(
        label="Paid-in capital increase",
        lead=part("Paid-in capital increase of {} common shares", "nstk_ostk_cnt"),
        parts=(
            part("{} other shares", "nstk_estk_cnt"),
            part("{} of shares before", "dilution_pct"),
            part("raising {}", "proceeds"),
            part("{}", "ic_mthn"),
        ),
        terms=(
            ("new_shares", "nstk_ostk_cnt"),
            ("new_other_shares", "nstk_estk_cnt"),
            ("shares_before", "bfic_tisstk_ostk"),
            ("dilution_pct", "dilution_pct"),
            ("proceeds", "proceeds"),
            ("method", "ic_mthn"),
        ),
        derived=(
            total("proceeds", *_FUNDING),
            ratio("dilution_pct", "nstk_ostk_cnt", "bfic_tisstk_ostk"),
        ),
    ),
    "bonus_issue": Presentation(
        label="Bonus issue",
        lead=part("Bonus issue of {} common shares", "nstk_ostk_cnt"),
        parts=(
            part("{} other shares", "nstk_estk_cnt"),
            part("{} new shares per share", "nstk_ascnt_ps_ostk"),
            part("{} of shares before", "dilution_pct"),
        ),
        terms=(
            ("new_shares", "nstk_ostk_cnt"),
            ("new_other_shares", "nstk_estk_cnt"),
            ("shares_per_share", "nstk_ascnt_ps_ostk"),
            ("shares_before", "bfic_tisstk_ostk"),
            ("dilution_pct", "dilution_pct"),
        ),
        derived=(ratio("dilution_pct", "nstk_ostk_cnt", "bfic_tisstk_ostk"),),
    ),
    "combined_paid_and_bonus_issue": Presentation(
        label="Paid-in and bonus issue",
        lead=part("Paid-in issue of {} common shares", "piic_nstk_ostk_cnt"),
        parts=(
            part("bonus issue of {} common shares", "fric_nstk_ostk_cnt"),
            part("{} bonus shares per share", "fric_nstk_ascnt_ps_ostk"),
            part("raising {}", "proceeds"),
            part("{}", "piic_ic_mthn"),
        ),
        terms=(
            ("paid_in_shares", "piic_nstk_ostk_cnt"),
            ("bonus_shares", "fric_nstk_ostk_cnt"),
            ("bonus_per_share", "fric_nstk_ascnt_ps_ostk"),
            ("shares_before", "piic_bfic_tisstk_ostk"),
            ("proceeds", "proceeds"),
            ("method", "piic_ic_mthn"),
        ),
        derived=(total("proceeds", *(f"piic_{name}" for name in _FUNDING)),),
    ),
    "equity_offering_registration": _offering("Equity offering registration", "Equity offering"),
    "depositary_receipt_registration": _offering(
        "Depositary receipt registration", "Depositary receipt offering"
    ),
    "convertible_bond": Presentation(
        label="Convertible bond",
        lead=part("{} convertible bond", "bd_fta"),
        parts=(
            part("series {}", "bd_tm"),
            part("{}", "bdis_mthn"),
            part("coupon {}", "bd_intr_ex"),
            part("YTM {}", "bd_intr_sf"),
            part("conversion price {}", "cv_prc"),
            part("{} new shares", "cvisstk_cnt"),
            part("{} of total shares", "cvisstk_tisstk_vs"),
            part("convertible {} to {}", "cvrqpd_bgd", "cvrqpd_edd"),
            part("refixing floor {}", "act_mktprcfl_cvprc_lwtrsprc"),
        ),
        terms=(
            ("face_value", "bd_fta"),
            ("series", "bd_tm"),
            ("coupon_pct", "bd_intr_ex"),
            ("ytm_pct", "bd_intr_sf"),
            ("conversion_price", "cv_prc"),
            ("conversion_shares", "cvisstk_cnt"),
            ("dilution_pct", "cvisstk_tisstk_vs"),
            ("refixing_floor", "act_mktprcfl_cvprc_lwtrsprc"),
            ("method", "bdis_mthn"),
        ),
    ),
    "bond_with_warrants": Presentation(
        label="Bond with warrants",
        lead=part("{} bond with warrants", "bd_fta"),
        parts=(
            part("series {}", "bd_tm"),
            part("{}", "bdis_mthn"),
            part("coupon {}", "bd_intr_ex"),
            part("YTM {}", "bd_intr_sf"),
            part("exercise price {}", "ex_prc"),
            part("{} new shares", "nstk_isstk_cnt"),
            part("{} of total shares", "nstk_isstk_tisstk_vs"),
            part("exercisable {} to {}", "expd_bgd", "expd_edd"),
            part("refixing floor {}", "act_mktprcfl_cvprc_lwtrsprc"),
        ),
        terms=(
            ("face_value", "bd_fta"),
            ("series", "bd_tm"),
            ("coupon_pct", "bd_intr_ex"),
            ("ytm_pct", "bd_intr_sf"),
            ("exercise_price", "ex_prc"),
            ("warrant_shares", "nstk_isstk_cnt"),
            ("dilution_pct", "nstk_isstk_tisstk_vs"),
            ("refixing_floor", "act_mktprcfl_cvprc_lwtrsprc"),
            ("method", "bdis_mthn"),
        ),
    ),
    "exchangeable_bond": Presentation(
        label="Exchangeable bond",
        lead=part("{} exchangeable bond", "bd_fta"),
        parts=(
            part("series {}", "bd_tm"),
            part("{}", "bdis_mthn"),
            part("coupon {}", "bd_intr_ex"),
            part("YTM {}", "bd_intr_sf"),
            part("exchange price {}", "ex_prc"),
            part("into {} shares of {}", "extg_stkcnt", "extg"),
            part("{} of total shares", "extg_tisstk_vs"),
            part("exchangeable {} to {}", "exrqpd_bgd", "exrqpd_edd"),
        ),
        terms=(
            ("face_value", "bd_fta"),
            ("series", "bd_tm"),
            ("coupon_pct", "bd_intr_ex"),
            ("ytm_pct", "bd_intr_sf"),
            ("exchange_price", "ex_prc"),
            ("exchange_shares", "extg_stkcnt"),
            ("exchange_target", "extg"),
            ("target_pct", "extg_tisstk_vs"),
            ("method", "bdis_mthn"),
        ),
    ),
    # The catalog labels bd_intr_sf as the coupon and bd_intr_ex as the yield for this kind.
    "contingent_capital_bond": Presentation(
        label="Contingent capital bond",
        lead=part("{} contingent capital bond", "bd_fta"),
        parts=(
            part("series {}", "bd_tm"),
            part("coupon {}", "bd_intr_sf"),
            part("YTM {}", "bd_intr_ex"),
            part("write-down scope: {}", "dbtrs_sc"),
        ),
        terms=(
            ("face_value", "bd_fta"),
            ("series", "bd_tm"),
            ("coupon_pct", "bd_intr_sf"),
            ("ytm_pct", "bd_intr_ex"),
            ("write_down_scope", "dbtrs_sc"),
        ),
    ),
    # One record per tranche (records.py); the series leads the terms so that calendar
    # items, which show the first few terms, tell tranches apart.
    "debt_offering_registration": Presentation(
        label="Debt offering registration",
        lead=part("Debt offering of {} {}", "fta", "bdnmn"),
        parts=(
            part("series {}", "tm"),
            part("coupon {}", "intr"),
            part("yield {}", "isrr"),
            part("rating {}", "cdrt_int"),
            part("underwriter {}", "udtintnm"),
        ),
        terms=(
            ("face_value", "fta"),
            ("series", "tm"),
            ("coupon_pct", "intr"),
            ("offer_amount", "slta"),
            ("yield_pct", "isrr"),
            ("security", "bdnmn"),
            ("rating", "cdrt_int"),
            ("underwriter", "udtintnm"),
        ),
    ),
    "treasury_stock_acquisition": Presentation(
        label="Treasury stock acquisition",
        lead=part("Buyback of {} common shares", "aqpln_stk_ostk"),
        parts=(
            part("{} other shares", "aqpln_stk_estk"),
            part("about {}", "amount"),
            part("{}", "aq_mth"),
            part("purpose: {}", "aq_pp"),
        ),
        terms=(
            ("shares", "aqpln_stk_ostk"),
            ("other_shares", "aqpln_stk_estk"),
            ("amount", "amount"),
            ("method", "aq_mth"),
            ("purpose", "aq_pp"),
            ("broker", "cs_iv_bk"),
            ("daily_limit", "d1_prodlm_ostk"),
        ),
        derived=(total("amount", "aqpln_prc_ostk", "aqpln_prc_estk"),),
    ),
    "treasury_stock_disposal": Presentation(
        label="Treasury stock disposal",
        lead=part("Disposal of {} common treasury shares", "dppln_stk_ostk"),
        parts=(
            part("{} other shares", "dppln_stk_estk"),
            part("at {}", "dpstk_prc_ostk"),
            part("about {}", "amount"),
            part("purpose: {}", "dp_pp"),
        ),
        terms=(
            ("shares", "dppln_stk_ostk"),
            ("other_shares", "dppln_stk_estk"),
            ("price", "dpstk_prc_ostk"),
            ("amount", "amount"),
            ("purpose", "dp_pp"),
            ("on_market_shares", "dp_m_mkt"),
            ("block_trade_shares", "dp_m_ovtm"),
            ("otc_shares", "dp_m_otc"),
            ("other_method_shares", "dp_m_etc"),
        ),
        derived=(total("amount", "dppln_prc_ostk", "dppln_prc_estk"),),
    ),
    "treasury_trust_contract": Presentation(
        label="Treasury stock trust contract",
        lead=part("{} treasury stock trust contract", "ctr_prc"),
        parts=(part("with {}", "ctr_cns_int"), part("purpose: {}", "ctr_pp")),
        terms=(("amount", "ctr_prc"), ("trustee", "ctr_cns_int"), ("purpose", "ctr_pp")),
    ),
    "treasury_trust_termination": Presentation(
        label="Treasury trust termination",
        lead=part("Termination of a {} treasury stock trust", "ctr_prc_bfcc"),
        parts=(
            part("{} after termination", "ctr_prc_atcc"),
            part("with {}", "cc_int"),
            part("purpose: {}", "cc_pp"),
            part("assets returned as {}", "tp_rm_atcc"),
        ),
        terms=(
            ("amount_before", "ctr_prc_bfcc"),
            ("amount_after", "ctr_prc_atcc"),
            ("trustee", "cc_int"),
            ("purpose", "cc_pp"),
            ("return_method", "tp_rm_atcc"),
        ),
    ),
    "capital_reduction": Presentation(
        label="Capital reduction",
        lead=part("Capital reduction of {} common shares", "crstk_ostk_cnt"),
        parts=(
            part("ratio {}", "cr_rt_ostk"),
            part("shares {} to {}", "bfcr_tisstk_ostk", "atcr_tisstk_ostk"),
            part("capital {} to {}", "bfcr_cpt", "atcr_cpt"),
            part("reason: {}", "cr_rs"),
        ),
        terms=(
            ("shares_reduced", "crstk_ostk_cnt"),
            ("other_shares_reduced", "crstk_estk_cnt"),
            ("reduction_pct", "cr_rt_ostk"),
            ("shares_before", "bfcr_tisstk_ostk"),
            ("shares_after", "atcr_tisstk_ostk"),
            ("capital_before", "bfcr_cpt"),
            ("capital_after", "atcr_cpt"),
            ("reason", "cr_rs"),
            ("method", "cr_mth"),
        ),
    ),
}
"""Presentations of the capital_raise, convertible_and_hybrid_debt, buyback, and
capital_reduction kinds."""
