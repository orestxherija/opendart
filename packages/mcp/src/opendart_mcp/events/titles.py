"""Map filing titles from the filing index to the event kinds that report them.

The English API titles major-issue reports by decision ("Decision on Issuance of Convertible
Bonds", "[Corrected description]Decision on Capital Increase with Consideration") and
registration statements by security ("Registration Statement (Equity securities)"). Rules
are tried in order and the first match wins: each lists words that must all appear and words
that must not, matched against the case-folded title without its leading bracketed markers.
Korean titles are matched without spaces. Several major-issue reports have no structured
service (treasury convertible bond deals, donations, hybrid capital securities), nor do
Fair Trade Act disclosures filed alongside them ("Decision on Acquisition of Non-current
Assets"); their titles map to no kind.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from opendart_mcp.registry import EventKind

type Rule = tuple[EventKind, tuple[str, ...], tuple[str, ...]]

_LEADING_MARKERS: Final = re.compile(r"^(?:\s*\[[^\]]*\])+")
_TREASURY: Final = ("treasury", "자기")
_REGISTRATIONS: Final[tuple[Rule, ...]] = (
    ("equity_offering_registration", ("registration statement", "equity securities"), ()),
    ("depositary_receipt_registration", ("registration statement", "depositary"), ()),
    ("debt_offering_registration", ("registration statement", "debt securities"), ()),
    ("merger_registration", ("registration statement", "merger"), ()),
    ("split_registration", ("registration statement", "split"), ()),
    ("split_registration", ("registration statement", "division"), ()),
    ("share_swap_registration", ("registration statement", "swap"), ()),
    ("share_swap_registration", ("registration statement", "exchange"), ()),
    ("share_swap_registration", ("registration statement", "transfer"), ()),
    ("equity_offering_registration", ("증권신고서", "지분증권"), ()),
    ("depositary_receipt_registration", ("증권신고서", "증권예탁증권"), ()),
    ("debt_offering_registration", ("증권신고서", "채무증권"), ()),
    ("merger_registration", ("증권신고서", "합병"), ()),
    ("split_registration", ("증권신고서", "분할"), ()),
    ("share_swap_registration", ("증권신고서", "교환"), ()),
)
_CAPITAL: Final[tuple[Rule, ...]] = (
    ("convertible_bond", ("convertible bond",), _TREASURY),
    ("bond_with_warrants", ("bonds with warrants",), _TREASURY),
    ("exchangeable_bond", ("exchangeable bond",), _TREASURY),
    ("contingent_capital_bond", ("contingent capital",), ()),
    ("combined_paid_and_bonus_issue", ("without consideration", "paid-in"), ()),
    ("combined_paid_and_bonus_issue", ("with and without consideration",), ()),
    ("bonus_issue", ("capital increase without consideration",), ()),
    ("bonus_issue", ("bonus issue",), ()),
    ("rights_or_third_party_issue", ("capital increase with consideration",), ()),
    ("rights_or_third_party_issue", ("paid-in capital increase",), ()),
    ("capital_reduction", ("capital reduction",), ()),
    ("treasury_trust_termination", ("trust contract", "termination"), ()),
    ("treasury_trust_contract", ("trust contract",), ()),
    ("treasury_stock_acquisition", ("acquisition of treasury stock",), ()),
    ("treasury_stock_disposal", ("disposal of treasury stock",), ()),
)
_DEALS: Final[tuple[Rule, ...]] = (
    ("split_merger", ("split", "merger"), ()),
    ("split_merger", ("division", "merger"), ()),
    ("split_off", ("split",), ()),
    ("split_off", ("division",), ()),
    ("merger", ("merger",), ()),
    ("share_swap_or_transfer", ("swap",), ()),
    ("share_swap_or_transfer", ("exchange or transfer of stock",), ()),
    ("share_swap_or_transfer", ("comprehensive stock exchange",), ()),
    ("business_acquisition", ("acquisition of business",), ()),
    ("business_transfer", ("transfer of business",), ()),
    ("acquire_equity_linked_bonds", ("acquisition of bonds related to stock",), ()),
    ("acquire_equity_linked_bonds", ("acquire stock-related bonds",), ()),
    ("transfer_equity_linked_bonds", ("transfer of bonds related to stock",), ()),
    ("transfer_equity_linked_bonds", ("transfer stock-related bonds",), ()),
    ("acquire_other_company_shares", ("acquisition of", "other corporation"), ()),
    ("transfer_other_company_shares", ("transfer of", "other corporation"), ()),
    ("acquire_tangible_assets", ("acquisition of tangible assets",), ()),
    ("transfer_tangible_assets", ("transfer of tangible assets",), ()),
    ("asset_deal_put_back_option", ("put back",), ()),
    ("asset_deal_put_back_option", ("put-back",), ()),
    ("asset_deal_put_back_option", ("assets (other)",), ()),
)
_DISTRESS: Final[tuple[Rule, ...]] = (
    ("rehabilitation_filing", ("rehabilitation",), ()),
    ("creditor_workout_suspension", ("administrative proceedings", "interrupt"), ()),
    ("creditor_workout_suspension", ("administrative proceedings", "suspen"), ()),
    ("creditor_workout_start", ("administrative proceedings",), ()),
    ("dissolution_cause", ("dissolution",), ()),
    ("business_suspension", ("business suspension",), ()),
    ("business_suspension", ("suspension of business",), ()),
    ("default_or_bankruptcy", ("bankruptcy",), ()),
    ("default_or_bankruptcy", ("default",), ()),
    ("default_or_bankruptcy", ("dishonor",), ()),
    ("lawsuit", ("lawsuit",), ()),
    ("lawsuit", ("litigation",), ()),
    ("overseas_delisting_decision", ("delist", "decision"), ()),
    ("overseas_delisting", ("delist",), ()),
    ("overseas_listing_decision", ("listing", "decision", "foreign"), ()),
    ("overseas_listing_decision", ("listing", "decision", "overseas"), ()),
    ("overseas_listing_completed", ("listing", "foreign"), ()),
    ("overseas_listing_completed", ("listing", "overseas"), ()),
)
_KOREAN: Final[tuple[Rule, ...]] = (
    ("convertible_bond", ("전환사채권발행",), ("자기전환",)),
    ("bond_with_warrants", ("신주인수권부사채권발행",), ()),
    ("exchangeable_bond", ("교환사채권발행",), ()),
    ("contingent_capital_bond", ("조건부자본증권",), ()),
    ("combined_paid_and_bonus_issue", ("유무상증자",), ()),
    ("bonus_issue", ("무상증자",), ()),
    ("rights_or_third_party_issue", ("유상증자",), ()),
    ("capital_reduction", ("감자",), ()),
    ("treasury_trust_termination", ("신탁계약해지",), ()),
    ("treasury_trust_contract", ("신탁계약체결",), ()),
    ("treasury_stock_acquisition", ("자기주식취득",), ()),
    ("treasury_stock_disposal", ("자기주식처분",), ()),
    ("split_merger", ("분할합병",), ()),
    ("split_off", ("회사분할",), ()),
    ("merger", ("합병",), ()),
    ("share_swap_or_transfer", ("주식교환",), ()),
    ("share_swap_or_transfer", ("주식이전",), ()),
    ("business_acquisition", ("영업양수",), ()),
    ("business_transfer", ("영업양도",), ()),
    ("acquire_equity_linked_bonds", ("주권관련사채권양수",), ()),
    ("transfer_equity_linked_bonds", ("주권관련사채권양도",), ()),
    ("acquire_other_company_shares", ("출자증권양수",), ()),
    ("transfer_other_company_shares", ("출자증권양도",), ()),
    ("acquire_tangible_assets", ("유형자산양수",), ()),
    ("transfer_tangible_assets", ("유형자산양도",), ()),
    ("asset_deal_put_back_option", ("풋백옵션",), ()),
    ("default_or_bankruptcy", ("부도발생",), ()),
    ("rehabilitation_filing", ("회생절차",), ()),
    ("creditor_workout_suspension", ("관리절차중단",), ()),
    ("creditor_workout_start", ("관리절차개시",), ()),
    ("dissolution_cause", ("해산사유",), ()),
    ("business_suspension", ("영업정지",), ()),
    ("lawsuit", ("소송",), ()),
    ("overseas_delisting_decision", ("상장폐지결정",), ()),
    ("overseas_delisting", ("상장폐지",), ()),
    ("overseas_listing_decision", ("해외증권시장", "상장결정"), ()),
    ("overseas_listing_completed", ("해외증권시장", "상장"), ()),
)
RULES: Final[tuple[Rule, ...]] = (
    *_REGISTRATIONS,
    *_CAPITAL,
    *_DEALS,
    *_DISTRESS,
    *_KOREAN,
)
"""Title rules in matching order: (kind, required words, excluded words)."""


def plain_title(title: str) -> str:
    """Drop leading bracketed markers such as ``[Corrected description]`` from a title.

    Args:
        title (str): Filing title as listed.

    Returns:
        str: Title without leading markers, whitespace collapsed.
    """
    return " ".join(_LEADING_MARKERS.sub("", title).split())


def _normalize(title: str) -> str:
    """Prepare a title for matching.

    Args:
        title (str): Filing title as listed.

    Returns:
        str: Case-folded title without leading markers, followed by a copy without spaces
            so that Korean words match however they are spaced.
    """
    lowered = plain_title(title).casefold()
    return f"{lowered} | {lowered.replace(" ", "")}"


def kind_for_title(title: str) -> EventKind | None:
    """Find the event kind whose service reports a filing with this title.

    Args:
        title (str): Filing title from the filing index.

    Returns:
        EventKind | None: The kind, or None when no structured service covers the title.
    """
    text = _normalize(title)
    for kind, required, excluded in RULES:
        if all(word in text for word in required) and not any(word in text for word in excluded):
            return kind
    return None
