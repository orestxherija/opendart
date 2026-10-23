"""OpenDART's financial indicators: profitability, stability, growth, and activity.

``fnltt_singl_indx`` (one company) and ``fnltt_cmpny_indx`` (up to 100) return one indicator
category per call, for the requested period only, from fiscal 2022. Values are published in
percent, turnover ratios included (61.7 means 0.617 times), and are computed on year-to-date
amounts. The English indicator names are machine translations, so key indicators get
clearer labels and stable keys here. Answers for a period whose filing deadline is recent
are cached briefly, because values appear and change as companies file and amend.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from opendart_mcp.core.ttl import DAY
from opendart_mcp.domain.normalize import clean_text, parse_percent
from opendart_mcp.services.fanout import gather
from opendart_mcp.services.periods import periodic_ttl
from opendart_mcp.services.statements import Line, Report

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from opendart.models.financial_statements import (
        FnlttCmpnyIndxResponse,
        FnlttCmpnyIndxResponseListItem,
        FnlttSinglIndxResponse,
        FnlttSinglIndxResponseListItem,
    )
    from opendart_mcp.core.gateway import Gateway
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.periods import PeriodRef
    from opendart_mcp.services.companies import Company

    type Category = Literal["M210000", "M220000", "M230000", "M240000"]

CATEGORIES: Final[tuple[Category, ...]] = ("M210000", "M220000", "M230000", "M240000")
"""Indicator categories: profitability, stability, growth, and activity."""

PERCENT_NOTE: Final = "OpenDART publishes every indicator in percent, turnover ratios included (61.7 means 0.617 times), computed on year-to-date amounts; values are as published, not recomputed."
"""Note attached to results that show indicators."""


@dataclass(frozen=True, slots=True)
class Indicator:
    """A key indicator with a stable key and a clear English label.

    Attributes:
        key (str): Stable key, such as ``net_margin``.
        label (str): English label.
    """

    key: str
    label: str


KEY_INDICATORS: Final[Mapping[str, Indicator]] = MappingProxyType(
    {
        "M211300": Indicator("gross_margin", "Gross margin"),
        "M211200": Indicator("net_margin", "Net margin"),
        "M211550": Indicator("roe", "Return on equity"),
        "M212000": Indicator("operating_roa", "Operating profit to total assets"),
        "M211800": Indicator("sga_to_revenue", "SG&A to revenue"),
        "M221100": Indicator("debt_to_equity", "Debt-to-equity"),
        "M221000": Indicator("equity_ratio", "Equity to total assets"),
        "M221200": Indicator("current_ratio", "Current ratio"),
        "M221300": Indicator("quick_ratio", "Quick ratio"),
        "M221600": Indicator("interest_coverage", "Interest coverage"),
        "M231000": Indicator("revenue_growth", "Revenue growth"),
        "M231400": Indicator("operating_income_growth", "Operating profit growth"),
        "M231800": Indicator("net_income_growth", "Net profit growth"),
        "M233000": Indicator("total_asset_growth", "Total asset growth"),
        "M241000": Indicator("asset_turnover", "Total asset turnover"),
        "M241200": Indicator("inventory_turnover", "Inventory turnover"),
        "M451000": Indicator("dividend_payout", "Dividend payout ratio"),
    }
)
"""Key indicators by OpenDART indicator code, in reading order."""

PEER_INDICATORS: Final[tuple[str, ...]] = (
    "M211300",
    "M211200",
    "M211550",
    "M212000",
    "M221100",
    "M221200",
    "M231000",
    "M231400",
    "M231800",
    "M241000",
)
"""Indicator codes a concise peer table shows."""

_ORDER: Final = MappingProxyType({code: rank for rank, code in enumerate(KEY_INDICATORS)})


@dataclass(frozen=True, slots=True)
class IndicatorValue:
    """One published indicator value.

    Attributes:
        corp_code (str | None): Company the value belongs to.
        code (str): Indicator code, such as M211200.
        name (str): Upstream English name.
        value (float | None): Value in percent; None when unpublished or malformed.
    """

    corp_code: str | None
    code: str
    name: str
    value: float | None


def indicator_values(
    response: FnlttSinglIndxResponse | FnlttCmpnyIndxResponse | None,
) -> list[IndicatorValue]:
    """Normalize an indicator response; ``#########`` overflow values become None.

    Args:
        response (FnlttSinglIndxResponse | FnlttCmpnyIndxResponse | None): Upstream answer.

    Returns:
        list[IndicatorValue]: Values in upstream order.
    """
    rows: Sequence[FnlttSinglIndxResponseListItem | FnlttCmpnyIndxResponseListItem] = (
        (response.list or []) if response is not None else []
    )
    return [
        IndicatorValue(
            clean_text(row.corporation_code),
            code,
            clean_text(row.indicator_name) or code,
            parse_percent(row.indicator_value),
        )
        for row in rows
        if (code := clean_text(row.idx_code))
    ]


def label(code: str, name: str) -> str:
    """Label an indicator, preferring the clear label of a key indicator.

    Args:
        code (str): Indicator code.
        name (str): Upstream English name.

    Returns:
        str: Display label.
    """
    known = KEY_INDICATORS.get(code)
    return known.label if known is not None else name


def key(code: str) -> str:
    """Give an indicator a stable column key.

    Args:
        code (str): Indicator code.

    Returns:
        str: Key of a key indicator, else the lowercase code.
    """
    known = KEY_INDICATORS.get(code)
    return known.key if known is not None else code.lower()


def rank(code: str, position: int) -> int:
    """Order key indicators first, then the rest in upstream order.

    Args:
        code (str): Indicator code.
        position (int): Upstream position.

    Returns:
        int: Sort position; key indicators rank below ``len(KEY_INDICATORS)``.
    """
    return _ORDER.get(code, len(_ORDER) + position)


def _single_call(
    gateway: Gateway, corp_code: str, ref: PeriodRef, *, category: Category, ttl: float
) -> Callable[[], Awaitable[FnlttSinglIndxResponse | None]]:
    """Bind one single-company indicator call.

    Args:
        gateway (Gateway): Upstream access.
        corp_code (str): Company.
        ref (PeriodRef): Period.
        category (Category): Indicator category.
        ttl (float): Cache lifetime in seconds.

    Returns:
        Callable[[], Awaitable[FnlttSinglIndxResponse | None]]: Call to await.
    """

    async def call() -> FnlttSinglIndxResponse | None:
        """Fetch this category of indicators for one company.

        Returns:
            FnlttSinglIndxResponse | None: Upstream response, or None when no data is
                available.

        Raises:
            ServerError: The upstream request fails or is rejected.
        """
        return await gateway.call(
            ttl,
            gateway.sdk.financial_statements.fnltt_singl_indx,
            corporation_code=corp_code,
            fiscal_year=str(ref.fiscal_year),
            report_period=ref.report_code,
            indicator_category_code=category,
        )

    return call


async def company_indicators(state: AppState, company: Company, ref: PeriodRef) -> Report | None:
    """Fetch all four indicator categories for one company and period.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Period.

    Returns:
        Report | None: One line per indicator, or None when nothing is published.
    """
    gateway = state.require_gateway()
    ttl = periodic_ttl(state, company, ref)
    calls = [
        _single_call(gateway, company.corp_code, ref, category=code, ttl=ttl) for code in CATEGORIES
    ]
    values = [value for response in await gather(calls) for value in indicator_values(response)]
    if not values:
        return None
    lines = [
        Line(
            key=item.code,
            account=label(item.code, item.name),
            account_id=item.code,
            kind="percent",
            rank=rank(item.code, position),
            values={ref: item.value},
            name=item.name,
        )
        for position, item in enumerate(values)
    ]
    return Report(lines)


def _peer_call(
    gateway: Gateway, corp_codes: Sequence[str], ref: PeriodRef, *, category: Category, ttl: float
) -> Callable[[], Awaitable[FnlttCmpnyIndxResponse | None]]:
    """Bind one multi-company indicator call.

    Args:
        gateway (Gateway): Upstream access.
        corp_codes (Sequence[str]): Companies, at most 100.
        ref (PeriodRef): Period.
        category (Category): Indicator category.
        ttl (float): Cache lifetime in seconds.

    Returns:
        Callable[[], Awaitable[FnlttCmpnyIndxResponse | None]]: Call to await.
    """

    async def call() -> FnlttCmpnyIndxResponse | None:
        """Fetch this category of indicators for a group of companies.

        Returns:
            FnlttCmpnyIndxResponse | None: Upstream response, or None when no data is
                available.

        Raises:
            ServerError: The upstream request fails or is rejected.
        """
        return await gateway.call(
            ttl,
            gateway.sdk.financial_statements.fnltt_cmpny_indx,
            corporation_codes=list(corp_codes),
            fiscal_year=str(ref.fiscal_year),
            report_period=ref.report_code,
            indicator_category_code=category,
        )

    return call


def peer_ttl(state: AppState, companies: Sequence[Company], ref: PeriodRef) -> float:
    """Choose how long to cache a multi-company answer for one period.

    The answer gains rows as companies file, so it lives as briefly as its most recent
    member's data: filing-list lifetime while any company's deadline is recent.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Companies in the call.
        ref (PeriodRef): Period.

    Returns:
        float: Shortest cache lifetime among the companies, in seconds.
    """
    return min((periodic_ttl(state, company, ref) for company in companies), default=DAY)


async def peer_indicators(
    state: AppState,
    companies: Sequence[Company],
    ref: PeriodRef,
    *,
    categories: Sequence[Category] = CATEGORIES,
) -> list[IndicatorValue]:
    """Fetch indicator categories for several companies and one period.

    Args:
        state (AppState): Server state.
        companies (Sequence[Company]): Companies, at most 100.
        ref (PeriodRef): Period.
        categories (Sequence[Category]): Categories to fetch.

    Returns:
        list[IndicatorValue]: Values tagged with their company's corp code.
    """
    gateway = state.require_gateway()
    codes = [company.corp_code for company in companies]
    ttl = peer_ttl(state, companies, ref)
    calls = [_peer_call(gateway, codes, ref, category=code, ttl=ttl) for code in categories]
    return [value for response in await gather(calls) for value in indicator_values(response)]
