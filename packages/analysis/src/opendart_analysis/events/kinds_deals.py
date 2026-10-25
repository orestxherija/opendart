"""Presentations for mergers, splits, share swaps, business transfers, and asset deals.

Headlines name the counterparty or target first, then the price, ratio, and size relative to
the company. Counterparty names, ratios, and purposes are often Korean text as filed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis.events.templates import Presentation, part

if TYPE_CHECKING:
    from opendart_analysis.catalog import EventKind


def _restructuring_registration(label: str, noun: str) -> Presentation:
    """Present a merger, share swap, or split registration statement.

    Args:
        label (str): Kind label.
        noun (str): Lead noun, such as "Merger".

    Returns:
        Presentation: Shared presentation of the three statements.
    """
    return Presentation(
        label=label,
        lead=part(noun + " registration: {}", "stn"),
        parts=(
            part("ratio {}", "rt_vl"),
            part("{} new {}", "cnt", "kndn"),
            part("appraisal price {}", "aprskh_prc"),
            part("valuation by {}", "exevl_int"),
        ),
        terms=(
            ("deal_type", "stn"),
            ("ratio", "rt_vl"),
            ("new_securities", "kndn"),
            ("quantity", "cnt"),
            ("appraisal_price", "aprskh_prc"),
            ("valuer", "exevl_int"),
            ("decision_filing", "rpt_rcpn"),
        ),
    )


def _tangible(label: str, *, buying: bool) -> Presentation:
    """Present an acquisition or transfer of tangible assets.

    Args:
        label (str): Kind label.
        buying (bool): True for an acquisition, False for a transfer.

    Returns:
        Presentation: Shared presentation of the two kinds.
    """
    prefix, verb, role, preposition = (
        ("inh", "Acquisition", "seller", "from") if buying else ("trf", "Sale", "buyer", "to")
    )
    price = "inhdtl_inhprc" if buying else "trfdtl_trfprc"
    assets = "inhdtl_tast_vs" if buying else "trfdtl_tast_vs"
    return Presentation(
        label=label,
        lead=part(verb + " of {}", "ast_nm"),
        parts=(
            part("{}", "ast_sen"),
            part("for {}", price),
            part("{} of total assets", assets),
            part(preposition + " {}", "dlptn_cmpnm"),
        ),
        terms=(
            ("asset", "ast_nm"),
            ("asset_type", "ast_sen"),
            ("price", price),
            ("assets_pct", assets),
            (role, "dlptn_cmpnm"),
            ("purpose", f"{prefix}_pp"),
        ),
    )


DEALS: Final[dict[EventKind, Presentation]] = {
    "merger": Presentation(
        label="Merger",
        lead=part("Merger with {}", "mgptncmp_cmpnm"),
        parts=(
            part("{}", "mg_stn"),
            part("ratio {}", "mg_rt"),
            part("{} new shares", "mgnstk_ostk_cnt"),
            part("appraisal price {}", "aprskh_plnprc"),
        ),
        terms=(
            ("counterparty", "mgptncmp_cmpnm"),
            ("relationship", "mgptncmp_rl_cmpn"),
            ("merger_type", "mg_stn"),
            ("ratio", "mg_rt"),
            ("new_shares", "mgnstk_ostk_cnt"),
            ("appraisal_price", "aprskh_plnprc"),
            ("purpose", "mg_pp"),
        ),
    ),
    "split_off": Presentation(
        label="Split-off",
        lead=part("Split-off creating {}", "dvfcmp_cmpnm"),
        parts=(
            part("{}", "dv_mth"),
            part("ratio {}", "dv_rt"),
            part("surviving company {}", "atdv_excmp_cmpnm"),
            part("capital reduction {}", "abcr_crrt"),
        ),
        terms=(
            ("new_company", "dvfcmp_cmpnm"),
            ("method", "dv_mth"),
            ("ratio", "dv_rt"),
            ("surviving_company", "atdv_excmp_cmpnm"),
            ("business_transferred", "dv_trfbsnprt_cn"),
            ("capital_reduction_pct", "abcr_crrt"),
        ),
    ),
    "split_merger": Presentation(
        label="Split-merger",
        lead=part("Split-merger with {}", "mgptncmp_cmpnm"),
        parts=(
            part("{}", "dvmg_mth"),
            part("ratio {}", "dvmg_rt"),
            part("{} new shares", "dvmgnstk_ostk_cnt"),
            part("appraisal price {}", "aprskh_plnprc"),
        ),
        terms=(
            ("counterparty", "mgptncmp_cmpnm"),
            ("relationship", "mgptncmp_rl_cmpn"),
            ("method", "dvmg_mth"),
            ("ratio", "dvmg_rt"),
            ("new_shares", "dvmgnstk_ostk_cnt"),
            ("business_transferred", "dv_trfbsnprt_cn"),
            ("appraisal_price", "aprskh_plnprc"),
        ),
    ),
    "share_swap_or_transfer": Presentation(
        label="Share swap or transfer",
        lead=part("Share swap or transfer with {}", "extr_tgcmp_cmpnm"),
        parts=(
            part("{}", "extr_stn"),
            part("ratio {}", "extr_rt"),
            part("parent after {}", "atextr_cpcmpnm"),
            part("appraisal price {}", "aprskh_plnprc"),
        ),
        terms=(
            ("counterparty", "extr_tgcmp_cmpnm"),
            ("relationship", "extr_tgcmp_rl_cmpn"),
            ("classification", "extr_sen"),
            ("swap_type", "extr_stn"),
            ("ratio", "extr_rt"),
            ("parent_after", "atextr_cpcmpnm"),
            ("appraisal_price", "aprskh_plnprc"),
            ("purpose", "extr_pp"),
        ),
    ),
    "business_acquisition": Presentation(
        label="Business acquisition",
        lead=part("Acquisition of the {} business", "inh_bsn"),
        parts=(
            part("for {}", "inh_prc"),
            part("from {}", "dlptn_cmpnm"),
            part("{} of assets", "ast_rt"),
            part("{} of sales", "sl_rt"),
        ),
        terms=(
            ("business", "inh_bsn"),
            ("price", "inh_prc"),
            ("counterparty", "dlptn_cmpnm"),
            ("relationship", "dlptn_rl_cmpn"),
            ("assets_pct", "ast_rt"),
            ("sales_pct", "sl_rt"),
            ("liabilities_pct", "dbt_rt"),
            ("purpose", "inh_pp"),
        ),
    ),
    "business_transfer": Presentation(
        label="Business transfer",
        lead=part("Transfer of the {} business", "trf_bsn"),
        parts=(
            part("for {}", "trf_prc"),
            part("to {}", "dlptn_cmpnm"),
            part("{} of assets", "ast_rt"),
            part("{} of sales", "sl_rt"),
        ),
        terms=(
            ("business", "trf_bsn"),
            ("price", "trf_prc"),
            ("counterparty", "dlptn_cmpnm"),
            ("relationship", "dlptn_rl_cmpn"),
            ("assets_pct", "ast_rt"),
            ("sales_pct", "sl_rt"),
            ("purpose", "trf_pp"),
        ),
    ),
    "merger_registration": _restructuring_registration("Merger registration", "Merger"),
    "share_swap_registration": _restructuring_registration("Share swap registration", "Share swap"),
    "split_registration": _restructuring_registration("Split registration", "Split"),
    "acquire_other_company_shares": Presentation(
        label="Acquisition of shares in another company",
        lead=part("Acquisition of shares in {}", "iscmp_cmpnm"),
        parts=(
            part("{} shares", "inhdtl_stkcnt"),
            part("for {}", "inhdtl_inhprc"),
            part("{} of equity", "inhdtl_ecpt_vs"),
            part("stake after {}", "atinh_eqrt"),
            part("from {}", "dlptn_cmpnm"),
        ),
        terms=(
            ("target", "iscmp_cmpnm"),
            ("relationship", "iscmp_rl_cmpn"),
            ("shares", "inhdtl_stkcnt"),
            ("price", "inhdtl_inhprc"),
            ("assets_pct", "inhdtl_tast_vs"),
            ("equity_pct", "inhdtl_ecpt_vs"),
            ("stake_after_pct", "atinh_eqrt"),
            ("seller", "dlptn_cmpnm"),
            ("purpose", "inh_pp"),
        ),
    ),
    "transfer_other_company_shares": Presentation(
        label="Transfer of shares in another company",
        lead=part("Sale of shares in {}", "iscmp_cmpnm"),
        parts=(
            part("{} shares", "trfdtl_stkcnt"),
            part("for {}", "trfdtl_trfprc"),
            part("{} of equity", "trfdtl_ecpt_vs"),
            part("stake after {}", "attrf_eqrt"),
            part("to {}", "dlptn_cmpnm"),
        ),
        terms=(
            ("target", "iscmp_cmpnm"),
            ("relationship", "iscmp_rl_cmpn"),
            ("shares", "trfdtl_stkcnt"),
            ("price", "trfdtl_trfprc"),
            ("assets_pct", "trfdtl_tast_vs"),
            ("equity_pct", "trfdtl_ecpt_vs"),
            ("stake_after_pct", "attrf_eqrt"),
            ("buyer", "dlptn_cmpnm"),
            ("purpose", "trf_pp"),
        ),
    ),
    "acquire_equity_linked_bonds": Presentation(
        label="Acquisition of equity-linked bonds",
        lead=part("Acquisition of {} of {}", "stkrtbd_kndn", "bdiscmp_cmpnm"),
        parts=(
            part("series {}", "tm"),
            part("face value {}", "inhdtl_bd_fta"),
            part("for {}", "inhdtl_inhprc"),
            part("from {}", "dlptn_cmpnm"),
        ),
        terms=(
            ("bond_type", "stkrtbd_kndn"),
            ("series", "tm"),
            ("issuer", "bdiscmp_cmpnm"),
            ("relationship", "bdiscmp_rl_cmpn"),
            ("face_value", "inhdtl_bd_fta"),
            ("price", "inhdtl_inhprc"),
            ("equity_pct", "inhdtl_ecpt_vs"),
            ("seller", "dlptn_cmpnm"),
            ("purpose", "inh_pp"),
        ),
    ),
    "transfer_equity_linked_bonds": Presentation(
        label="Transfer of equity-linked bonds",
        lead=part("Sale of {} of {}", "stkrtbd_kndn", "bdiscmp_cmpnm"),
        parts=(
            part("series {}", "tm"),
            part("face value {}", "trfdtl_bd_fta"),
            part("for {}", "trfdtl_trfprc"),
            part("to {}", "dlptn_cmpnm"),
        ),
        terms=(
            ("bond_type", "stkrtbd_kndn"),
            ("series", "tm"),
            ("issuer", "bdiscmp_cmpnm"),
            ("relationship", "bdiscmp_rl_cmpn"),
            ("face_value", "trfdtl_bd_fta"),
            ("price", "trfdtl_trfprc"),
            ("equity_pct", "trfdtl_ecpt_vs"),
            ("buyer", "dlptn_cmpnm"),
            ("purpose", "trf_pp"),
        ),
    ),
    "acquire_tangible_assets": _tangible("Tangible asset acquisition", buying=True),
    "transfer_tangible_assets": _tangible("Tangible asset transfer", buying=False),
    "asset_deal_put_back_option": Presentation(
        label="Asset deal or put-back option",
        lead=part("Asset deal or put-back option: {}", "rp_rsn"),
        parts=(part("price {}", "ast_inhtrf_prc"),),
        terms=(("reason", "rp_rsn"), ("price", "ast_inhtrf_prc")),
    ),
}
"""Presentations of the mna_and_restructuring and asset_and_investment_deals kinds."""
