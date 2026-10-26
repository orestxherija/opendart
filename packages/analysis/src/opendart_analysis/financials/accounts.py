"""Financial statement vocabulary: key accounts by XBRL ID and English or Korean name.

The English API returns English account names, but they differ between services (the
summary says "Sales" where the full statement says "Revenue") and companies, so lines are
matched by standard XBRL account ID first and by normalized name second. Full statements
arrive sorted by account ID rather than in presentation order; the key-account lists below
restore a reading order with the most decision-relevant lines first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

NON_STANDARD_ID: Final = "standard account code not used"
"""Marker OpenDART puts in ``account_id`` for company-specific accounts (any case)."""


@dataclass(frozen=True, slots=True)
class Metric:
    """A key financial line that derived metrics and peer tables use.

    Attributes:
        key (str): Stable key, such as ``revenue``.
        label (str): English label.
        ids (frozenset[str]): Standard XBRL account IDs.
        names (frozenset[str]): Normalized account names (see ``normalize``).
    """

    key: str
    label: str
    ids: frozenset[str]
    names: frozenset[str]


# Key, label, space-separated XBRL IDs, and space-separated normalized names.
_METRIC_SPECS: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "revenue",
        "Revenue",
        "ifrs-full_Revenue",
        "revenue revenues sales salesrevenue operatingrevenue operatingrevenues 매출액 영업수익",
    ),
    (
        "operating_income",
        "Operating profit",
        "dart_OperatingIncomeLoss",
        "operatingincome operatingprofit 영업이익",
    ),
    (
        "pretax_income",
        "Profit before tax",
        "ifrs-full_ProfitLossBeforeTax",
        "profitbeforeincometax profitbeforetax incomebeforeincometax 법인세차감전순이익 법인세비용차감전순이익",
    ),
    (
        "net_income",
        "Net profit",
        "ifrs-full_ProfitLoss",
        "profit netincome netprofit profitfortheyear profitfortheperiod 당기순이익",
    ),
    (
        "comprehensive_income",
        "Total comprehensive income",
        "ifrs-full_ComprehensiveIncome",
        "totalcomprehensiveincome comprehensiveincome 총포괄손익 총포괄이익",
    ),
    ("total_assets", "Total assets", "ifrs-full_Assets", "totalassets 자산총계"),
    (
        "total_liabilities",
        "Total liabilities",
        "ifrs-full_Liabilities",
        "totalliabilities 부채총계",
    ),
    ("total_equity", "Total equity", "ifrs-full_Equity", "totalequity 자본총계"),
    ("current_assets", "Current assets", "ifrs-full_CurrentAssets", "currentassets 유동자산"),
    (
        "current_liabilities",
        "Current liabilities",
        "ifrs-full_CurrentLiabilities",
        "currentliabilities 유동부채",
    ),
    (
        "non_current_assets",
        "Non-current assets",
        "ifrs-full_NoncurrentAssets",
        "noncurrentassets 비유동자산",
    ),
    (
        "non_current_liabilities",
        "Non-current liabilities",
        "ifrs-full_NoncurrentLiabilities",
        "noncurrentliabilities 비유동부채",
    ),
    ("issued_capital", "Issued capital", "ifrs-full_IssuedCapital", "issuedcapital 자본금"),
    (
        "retained_earnings",
        "Retained earnings",
        "ifrs-full_RetainedEarnings",
        "retainedearnings 이익잉여금 이익잉여금결손금",
    ),
)

METRICS: Final[tuple[Metric, ...]] = tuple(
    Metric(key, label, frozenset(ids.split()), frozenset(names.split()))
    for key, label, ids, names in _METRIC_SPECS
)
"""Key lines in summary reading order: income lines first, then the balance sheet."""

METRIC_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {metric.key: rank for rank, metric in enumerate(METRICS)}
)
"""Reading-order position of each metric key."""

_BY_ID: Final = MappingProxyType({i: metric for metric in METRICS for i in metric.ids})
_BY_NAME: Final = MappingProxyType({n: metric for metric in METRICS for n in metric.names})

KEY_ACCOUNTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "IS": (
            "ifrs-full_Revenue",
            "ifrs-full_CostOfSales",
            "ifrs-full_GrossProfit",
            "dart_TotalSellingGeneralAdministrativeExpenses",
            "dart_OperatingIncomeLoss",
            "ifrs-full_FinanceIncome",
            "ifrs-full_FinanceCosts",
            "ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
            "ifrs-full_ProfitLossBeforeTax",
            "ifrs-full_IncomeTaxExpenseContinuingOperations",
            "ifrs-full_ProfitLoss",
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "ifrs-full_ProfitLossAttributableToNoncontrollingInterests",
            "ifrs-full_BasicEarningsLossPerShare",
            "ifrs-full_DilutedEarningsLossPerShare",
        ),
        # Totals, liquidity and working capital, operating assets, investments in other
        # companies, every form of debt, and equity; companies use one of the alternatives.
        "BS": (
            "ifrs-full_Assets",
            "ifrs-full_CurrentAssets",
            "ifrs-full_CashAndCashEquivalents",
            "ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents",
            "ifrs-full_CurrentInvestments",
            "ifrs-full_CurrentTradeReceivables",
            "ifrs-full_TradeAndOtherCurrentReceivables",
            "ifrs-full_Inventories",
            "ifrs-full_NoncurrentAssets",
            "ifrs-full_PropertyPlantAndEquipment",
            "ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets",
            "ifrs-full_RightofuseAssets",
            "ifrs-full_IntangibleAssetsAndGoodwill",
            "ifrs-full_IntangibleAssetsOtherThanGoodwill",
            "ifrs-full_Goodwill",
            "ifrs-full_InvestmentAccountedForUsingEquityMethod",
            "ifrs-full_InvestmentsInSubsidiariesJointVenturesAndAssociates",
            "ifrs-full_Liabilities",
            "ifrs-full_CurrentLiabilities",
            "ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers",
            "ifrs-full_TradeAndOtherCurrentPayables",
            "ifrs-full_ShorttermBorrowings",
            "dart_CurrentLoansReceived",
            "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
            "ifrs-full_CurrentPortionOfLongtermBorrowings",
            "ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",
            "ifrs-full_CurrentLeaseLiabilities",
            "ifrs-full_NoncurrentLiabilities",
            "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
            "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived",
            "ifrs-full_LongtermBorrowings",
            "ifrs-full_NoncurrentLeaseLiabilities",
            "ifrs-full_Equity",
            "ifrs-full_EquityAttributableToOwnersOfParent",
            "ifrs-full_IssuedCapital",
            "ifrs-full_SharePremium",
            "dart_CapitalSurplus",
            "ifrs-full_RetainedEarnings",
            "ifrs-full_NoncontrollingInterests",
        ),
        "CF": (
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "ifrs-full_InterestPaidClassifiedAsOperatingActivities",
            "ifrs-full_IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
            "ifrs-full_CashFlowsFromUsedInInvestingActivities",
            "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
            "ifrs-full_CashFlowsFromUsedInFinancingActivities",
            "ifrs-full_DividendsPaidClassifiedAsFinancingActivities",
            "dart_AcquisitionOfTreasuryShares",
            "ifrs-full_IncreaseDecreaseInCashAndCashEquivalents",
            "ifrs-full_EffectOfExchangeRateChangesOnCashAndCashEquivalents",
            "dart_CashAndCashEquivalentsAtBeginningOfPeriodCf",
            "dart_CashAndCashEquivalentsAtEndOfPeriodCf",
        ),
        "CIS": (
            "ifrs-full_ProfitLoss",
            "ifrs-full_OtherComprehensiveIncome",
            "ifrs-full_ComprehensiveIncome",
            "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent",
            "ifrs-full_ComprehensiveIncomeAttributableToNoncontrollingInterests",
        ),
        "SCE": ("dart_EquityAtBeginningOfPeriod",),
    }
)
"""Key account IDs per statement type, in reading order."""

KEY_ACCOUNT_NAMES: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {"BS": MappingProxyType({"shorttermborrowings": "ifrs-full_ShorttermBorrowings"})}
)
"""Company-specific accounts (no standard ID) that rank like a key account, by normalized name."""

EQUITY_AT_END: Final = "ifrs-full_Equity"
"""Closing line of the statement of changes in equity."""

TOTAL_COMPONENT: Final = "Total"
"""Equity component label for whole-equity movements."""

# Equity components named in account_detail, matched by substring in this order.
_COMPONENTS: Final[tuple[tuple[str, str], ...]] = (
    ("비지배", "Non-controlling interests"),
    ("non-controlling", "Non-controlling interests"),
    ("자본금", "Issued capital"),
    ("issued capital", "Issued capital"),
    ("주식발행초과금", "Share premium"),
    ("share premium", "Share premium"),
    ("자본잉여금", "Capital surplus"),
    ("이익잉여금", "Retained earnings"),
    ("retained", "Retained earnings"),
    ("자기주식", "Treasury shares"),
    ("신종자본", "Hybrid capital securities"),
    ("기타", "Other components of equity"),
    ("other", "Other components of equity"),
    ("지배기업", "Owners of the parent"),
    ("소유주", "Owners of the parent"),
)
_WHOLE_EQUITY: Final = frozenset({"자본", "자본합계", "합계", "총계", "자본의구성요소", "equity"})
_TAG = re.compile(r"\[[^\]]*\]")
COMPONENT_ORDER: Final[tuple[str, ...]] = (
    TOTAL_COMPONENT,
    "Owners of the parent",
    "Issued capital",
    "Share premium",
    "Capital surplus",
    "Retained earnings",
    "Other components of equity",
    "Treasury shares",
    "Hybrid capital securities",
    "Non-controlling interests",
)
"""Display order of equity components."""


def normalize(name: str) -> str:
    """Reduce an account name to lowercase letters and digits, dropping "(loss)".

    Args:
        name (str): Account name as filed.

    Returns:
        str: Normalized name, for example ``profitbeforeincometax``.
    """
    lowered = name.lower().replace("(loss)", "")
    return "".join(character for character in lowered if character.isalnum())


def standard_id(account_id: str | None) -> str | None:
    """Keep a standard XBRL account ID, dropping OpenDART's "not used" marker.

    Args:
        account_id (str | None): Upstream ``account_id``.

    Returns:
        str | None: The ID, or None for blanks and company-specific accounts.
    """
    text = (account_id or "").strip()
    if not text or NON_STANDARD_ID in text.lower():
        return None
    return text


def metric_of(account_id: str | None, account: str) -> Metric | None:
    """Identify the key metric a line reports, by XBRL ID first and name second.

    Args:
        account_id (str | None): Standard XBRL account ID, if any.
        account (str): Account name.

    Returns:
        Metric | None: The metric, or None for other lines.
    """
    by_id = _BY_ID.get(account_id or "")
    return by_id if by_id is not None else _BY_NAME.get(normalize(account))


def is_per_share(account_id: str | None, account: str) -> bool:
    """Tell whether a line is a per-share amount, such as earnings per share.

    Args:
        account_id (str | None): Standard XBRL account ID, if any.
        account (str): Account name.

    Returns:
        bool: True for per-share lines, which are never scaled.
    """
    return "PerShare" in (account_id or "") or "per share" in account.lower()


def component(detail: str | None) -> str | None:
    """Name the equity component of a statement-of-changes-in-equity line.

    ``account_detail`` is a Korean member path even in the English API, such as
    ``자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]|이익잉여금 [구성요소]``;
    its last segment names the column of the statement.

    Args:
        detail (str | None): Upstream ``account_detail``; ``-`` outside the statement.

    Returns:
        str | None: English component label, the Korean segment when unknown, or None.
    """
    segment = _TAG.sub("", (detail or "").rsplit("|", 1)[-1]).strip()
    if not segment or segment == "-":
        return None
    compact = "".join(segment.split()).lower()
    if compact in _WHOLE_EQUITY or compact.endswith("재무제표"):
        return TOTAL_COMPONENT
    lowered = segment.lower()
    return next((label for marker, label in _COMPONENTS if marker in lowered), segment)
