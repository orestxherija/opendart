"""Filing titles from the English (and Korean) index map to the event kinds that report them."""

from __future__ import annotations

import pytest

from opendart_analysis.catalog import EVENT_KINDS
from opendart_mcp.events.titles import RULES, kind_for_title, plain_title


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ("Decision on Issuance of Convertible Bonds", "convertible_bond"),
        ("[Corrected description]Decision on Issuance of Convertible Bonds", "convertible_bond"),
        ("[Corrected attachment]Decision on Issuance of Bonds with Warrants", "bond_with_warrants"),
        ("Decision on Issuance of Exchangeable Bonds", "exchangeable_bond"),
        (
            "[Corrected description]Decision on Issuance of Amortized Contingent Capital Securities",
            "contingent_capital_bond",
        ),
        ("Decision on Capital Increase with Consideration", "rights_or_third_party_issue"),
        ("Decision on Paid-in Capital Increase", "rights_or_third_party_issue"),
        ("Decision on Capital Increase without Consideration", "bonus_issue"),
        (
            "Decision on Paid-in Capital Increase/Capital Increase without Consideration",
            "combined_paid_and_bonus_issue",
        ),
        ("Decision on Capital Reduction", "capital_reduction"),
        (
            "Decision on Entering into Trust Contract for Acquisition of Treasury Stock",
            "treasury_trust_contract",
        ),
        (
            "Decision on Termination of Trust Contract for Acquisition of Treasury Stock",
            "treasury_trust_termination",
        ),
        ("Decision on Acquisition of Treasury Stock", "treasury_stock_acquisition"),
        ("Decision on Disposal of Treasury Stock", "treasury_stock_disposal"),
        ("[Corrected attachment]Decision on Merger", "merger"),
        ("Decision on Split-off", "split_off"),
        ("Decision on Merger after Split-off", "split_merger"),
        ("Decision to swap or transfer stocks", "share_swap_or_transfer"),
        ("Decision on Acquisition of Business", "business_acquisition"),
        ("Decision on Transfer of Business", "business_transfer"),
        ("Decision on Acquisition of Bonds related to Stocks", "acquire_equity_linked_bonds"),
        ("Decision on Transfer of Bonds related to Stocks", "transfer_equity_linked_bonds"),
        (
            "Decision on Acquisition of Stocks or Capital Contribution Certificates of Other Corporations",
            "acquire_other_company_shares",
        ),
        (
            "Decision on Transfer of Shares or Investment Certificates of Other Corporations",
            "transfer_other_company_shares",
        ),
        ("Decision on Acquisition of Tangible Assets", "acquire_tangible_assets"),
        ("Decision on Transfer of Tangible Assets", "transfer_tangible_assets"),
        (
            "Report on Major Issues (Transfer and acquisition of assets (other), put back option)",
            "asset_deal_put_back_option",
        ),
        ("Bankruptcy Occurrence", "default_or_bankruptcy"),
        ("Application for Commencement of Rehabilitation Procedures", "rehabilitation_filing"),
        (
            "Commencement of Administrative Proceedings by Creditor Banks, etc.",
            "creditor_workout_start",
        ),
        (
            "Interruption of Administrative Proceedings by Creditor Banks, etc.",
            "creditor_workout_suspension",
        ),
        ("Occurrence of Dissolution Cause", "dissolution_cause"),
        ("[Corrected description]Report on business suspension", "business_suspension"),
        ("Lawsuit Filing, etc.", "lawsuit"),
        (
            "Decision on Listing of Stocks, Etc. on a Foreign Securities Exchange",
            "overseas_listing_decision",
        ),
        (
            "The Listing of Stocks, Etc. on a Foreign Securities Exchange",
            "overseas_listing_completed",
        ),
        (
            "Decision to Delist Stocks, Etc. on a Foreign Securities Exchange",
            "overseas_delisting_decision",
        ),
        ("Delisting of Stocks, Etc. on a Foreign Securities Exchange", "overseas_delisting"),
        ("Registration Statement (Equity securities)", "equity_offering_registration"),
        (
            "[Conditions for issuance finalized]Registration Statement (Equity securities)",
            "equity_offering_registration",
        ),
        ("Registration Statement (Debt securities)", "debt_offering_registration"),
        ("Registration Statement (Depositary Receipts)", "depositary_receipt_registration"),
        ("[Corrected description]Registration Statement (Merger) ", "merger_registration"),
        ("Registration Statement (Division)", "split_registration"),
        (
            "Registration Statement (Comprehensive stock exchange/transfer)",
            "share_swap_registration",
        ),
        ("[기재정정]주요사항보고서(전환사채권발행결정)", "convertible_bond"),
        ("주요사항보고서 (유상증자결정)", "rights_or_third_party_issue"),
        ("[발행조건확정]증권신고서(지분증권)", "equity_offering_registration"),
    ],
)
def test_titles_map_to_kinds(title, kind):
    assert kind_for_title(title) == kind


@pytest.mark.parametrize(
    "title",
    [
        "Report on Major Issues (Decision on Acquisition of Treasury Convertible Bonds before Maturity)",
        "[Corrected description]Report on Major Issues (Decision on sale of Treasury Bonds with Warrants)",
        "Report on Major Issues (Decision on issuance of debt securities recognized as capital)",
        "Decision on Donation",
        # A Fair Trade Act disclosure: the put-back service has no row for it.
        "Decision on Acquisition of Non-current Assets",
        "[Corrected description]Decision on Acquisition of Non-current Assets",
        "Prospectus (Shelf Registration)",
        "Supplements to the Universal Shelf Registration Statement (Derivatives-linked securities - Equity-Linked Securities)",
        "Post-issuance report",
        "주요사항보고서(자기전환사채만기전취득결정)",
    ],
)
def test_reports_without_structured_services_map_to_nothing(title):
    assert kind_for_title(title) is None


def test_every_kind_has_a_title_rule():
    assert {kind for kind, _, _ in RULES} == set(EVENT_KINDS)


def test_plain_title_drops_leading_markers():
    assert plain_title("[Corrected description] [x]Decision  on Merger") == "Decision on Merger"
    assert plain_title("Decision on Merger [note]") == "Decision on Merger [note]"
