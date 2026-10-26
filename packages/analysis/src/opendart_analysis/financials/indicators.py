"""OpenDART's financial indicators: profitability, stability, growth, and activity.

OpenDART publishes indicators one category per request, for one company
(``fnltt_singl_indx``) or up to 100 (``fnltt_cmpny_indx``), for the requested period only,
from fiscal 2022. Values are published in percent, turnover ratios included (61.7 means
0.617 times), and are computed on year-to-date amounts. The English indicator names are
machine translations, so key indicators get clearer labels and stable keys here.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, Protocol

from opendart_analysis.domain.normalize import clean_text, parse_percent
from opendart_analysis.domain.periods import FIRST_INDICATOR_YEAR
from opendart_analysis.errors import MissingDataError
from opendart_analysis.extracts import gather_all
from opendart_analysis.financials.access import check_peer_count
from opendart_analysis.financials.chain import Span, chain, check_reports
from opendart_analysis.financials.history import StatementHistory
from opendart_analysis.financials.statements import Line, Report, merge
from opendart_analysis.reports import period_volatility
from opendart_analysis.upstream import no_progress

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Basis, ReportCode
    from opendart_analysis.reports import FiscalCompany, ResolvedPeriod
    from opendart_analysis.upstream import Progress, Volatility

    type Records = Sequence[IndicatorRecord] | None

type IndicatorCategory = Literal["M210000", "M220000", "M230000", "M240000"]
"""Indicator category: profitability, stability, growth, or activity."""

CATEGORIES: Final[tuple[IndicatorCategory, ...]] = ("M210000", "M220000", "M230000", "M240000")
"""Every indicator category, in that order."""

PERCENT_NOTE: Final = "OpenDART publishes every indicator in percent, turnover ratios included (61.7 means 0.617 times), computed on year-to-date amounts; values are as published, not recomputed."
"""Caveat to show with indicator values."""


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

_ORDER: Final = MappingProxyType({code: rank for rank, code in enumerate(KEY_INDICATORS)})


class IndicatorsUnavailableError(MissingDataError):
    """The requested period predates OpenDART's financial indicators.

    Attributes:
        fiscal_year (int | None): Requested fiscal year, if any.
        first_indicator_year (int): First fiscal year with indicators.
    """

    def __init__(self, fiscal_year: int | None) -> None:
        """Describe the unavailable indicators.

        Args:
            fiscal_year (int | None): Requested fiscal year, if any.
        """
        wanted = f"fiscal {fiscal_year}" if fiscal_year is not None else "the requested period"
        message = f"OpenDART publishes financial indicators from fiscal {FIRST_INDICATOR_YEAR}, so {wanted} has none."
        super().__init__(message)
        self.fiscal_year = fiscal_year
        self.first_indicator_year = FIRST_INDICATOR_YEAR


@dataclass(frozen=True, slots=True)
class IndicatorQuery:
    """One indicator category of one company for one period.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        fiscal_year (int): Fiscal-year label (``bsns_year``).
        report_code (ReportCode): Report code (``reprt_code``) of the period.
        category (IndicatorCategory): Indicator category.
    """

    corp_code: str
    fiscal_year: int
    report_code: ReportCode
    category: IndicatorCategory


@dataclass(frozen=True, slots=True)
class PeerIndicatorQuery:
    """One indicator category of several companies for one period.

    Attributes:
        corp_codes (tuple[str, ...]): 8-digit DART corporation codes, 1 to 100.
        fiscal_year (int): Fiscal-year label (``bsns_year``).
        report_code (ReportCode): Report code (``reprt_code``) of the period.
        category (IndicatorCategory): Indicator category.
    """

    corp_codes: tuple[str, ...]
    fiscal_year: int
    report_code: ReportCode
    category: IndicatorCategory

    def __post_init__(self) -> None:
        """Reject a company count OpenDART cannot serve in one request.

        Raises:
            ValueError: ``corp_codes`` is empty or longer than 100.
        """
        check_peer_count(len(self.corp_codes))


class IndicatorRecord(Protocol):
    """The fields of one published indicator that analysis reads."""

    @property
    def corporation_code(self) -> str | None:
        """8-digit DART corporation code of the company."""
        ...

    @property
    def idx_code(self) -> str | None:
        """Indicator code, such as ``M211200``."""
        ...

    @property
    def indicator_name(self) -> str | None:
        """English indicator name as published."""
        ...

    @property
    def indicator_value(self) -> str | None:
        """Value in percent as text; ``#########`` when it overflows."""
        ...


class FetchIndicators(Protocol):
    """Fetch one indicator category of one company; bound by the caller to a data source."""

    async def __call__(
        self, query: IndicatorQuery, /, *, volatility: Volatility
    ) -> Sequence[IndicatorRecord] | None:
        """Return one category of a company's indicators for one period.

        Args:
            query (IndicatorQuery): Company, period, and category.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[IndicatorRecord] | None: Values, or None when the source has none.
        """
        ...


class FetchPeerIndicators(Protocol):
    """Fetch one indicator category of several companies; bound by the caller."""

    async def __call__(
        self, query: PeerIndicatorQuery, /, *, volatility: Volatility
    ) -> Sequence[IndicatorRecord] | None:
        """Return one category of several companies' indicators for one period.

        Args:
            query (PeerIndicatorQuery): Companies, period, and category.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[IndicatorRecord] | None: Values, or None when the source has none.
        """
        ...


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


def indicator_values(records: Iterable[IndicatorRecord] | None) -> list[IndicatorValue]:
    """Normalize published indicators; ``#########`` overflow values become None.

    Args:
        records (Iterable[IndicatorRecord] | None): Upstream values; None means none.

    Returns:
        list[IndicatorValue]: Values in upstream order, without rows lacking a code.
    """
    return [
        IndicatorValue(
            clean_text(row.corporation_code),
            code,
            clean_text(row.indicator_name) or code,
            parse_percent(row.indicator_value),
        )
        for row in records or ()
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
    """Give an indicator a stable key.

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


async def company_indicators(
    company: FiscalCompany, ref: PeriodRef, *, fetch_indicators: FetchIndicators, today: date
) -> Report | None:
    """Fetch all four indicator categories for one company and period, concurrently.

    Args:
        company (FiscalCompany): Company.
        ref (PeriodRef): Period.
        fetch_indicators (FetchIndicators): One category per call; asked with
            ``period_volatility`` of the period.
        today (date): Today in KST, which sets the period's volatility.

    Returns:
        Report | None: One percent line per indicator, key indicators ranked first, or None
            when nothing is published.
    """
    volatility = period_volatility(ref, fye_month=company.fye_month, today=today)

    answers = await gather_all(
        fetch_indicators(
            IndicatorQuery(company.corp_code, ref.fiscal_year, ref.report_code, category),
            volatility=volatility,
        )
        for category in CATEGORIES
    )
    values = [value for records in answers for value in indicator_values(records)]
    if not values:
        return None
    lines = tuple(
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
    )
    return Report(lines)


def peer_volatility(
    companies: Iterable[FiscalCompany], ref: PeriodRef, *, today: date
) -> Volatility:
    """Say how quickly a multi-company answer for one period can change.

    The answer gains rows as companies file, so it is as volatile as its most recent member's
    data: ``high`` while any company's filing window is open, else ``low``.

    Args:
        companies (Iterable[FiscalCompany]): Companies in the request.
        ref (PeriodRef): Period.
        today (date): Today in KST.

    Returns:
        Volatility: ``high`` or ``low``.
    """
    windows = (period_volatility(ref, fye_month=c.fye_month, today=today) for c in companies)
    return "high" if "high" in windows else "low"


async def peer_indicators(
    companies: Sequence[FiscalCompany],
    ref: PeriodRef,
    *,
    categories: Sequence[IndicatorCategory] = CATEGORIES,
    fetch_peer_indicators: FetchPeerIndicators,
    today: date,
) -> list[IndicatorValue]:
    """Fetch indicator categories for several companies and one period, concurrently.

    Args:
        companies (Sequence[FiscalCompany]): Companies, 1 to 100.
        ref (PeriodRef): Period.
        categories (Sequence[IndicatorCategory]): Categories to fetch, one call each.
        fetch_peer_indicators (FetchPeerIndicators): One category per call; asked with
            ``peer_volatility``.
        today (date): Today in KST, which sets the volatility.

    Returns:
        list[IndicatorValue]: Values tagged with their company's corp code.
    """
    codes = tuple(company.corp_code for company in companies)
    volatility = peer_volatility(companies, ref, today=today)

    answers = await gather_all(
        fetch_peer_indicators(
            PeerIndicatorQuery(codes, ref.fiscal_year, ref.report_code, category),
            volatility=volatility,
        )
        for category in categories
    )
    return [value for records in answers for value in indicator_values(records)]


async def indicator_history(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    years: int,
    fetch_indicators: FetchIndicators,
    today: date,
    progress: Progress | None = None,
) -> StatementHistory | None:
    """Read a company's published indicators over fiscal years, one column per year.

    Makes four calls per period: at most three candidate periods, then ``years - 1`` earlier
    fiscal years, none before 2022. Indicators have no basis, so the history's report has none.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        years (int): Fiscal years wanted, newest first, 1 to ``MAX_REPORTS``.
        fetch_indicators (FetchIndicators): One category per call.
        today (date): Today in KST, which sets each period's volatility.
        progress (Progress | None): Receives one message per period fetched.

    Returns:
        StatementHistory | None: Indicator lines, or None when no candidate period has any.

    Raises:
        ValueError: ``years`` is outside 1 to ``MAX_REPORTS``.
        IndicatorsUnavailableError: Every candidate period predates fiscal 2022.
    """
    check_reports(years)
    fiscal_years = [ref.fiscal_year for ref in resolved.candidates]
    if fiscal_years and max(fiscal_years) < FIRST_INDICATOR_YEAR:
        raise IndicatorsUnavailableError(max(fiscal_years))

    async def fetch(ref: PeriodRef, basis: Basis) -> Report | None:
        """Fetch one period's indicators; indicators have no basis.

        Args:
            ref (PeriodRef): Period to fetch.
            basis (Basis): Ignored.

        Returns:
            Report | None: Indicator report, or None when nothing is published.
        """
        del basis
        return await company_indicators(
            company, ref, fetch_indicators=fetch_indicators, today=today
        )

    span = Span(years=years, step=1, earliest=FIRST_INDICATOR_YEAR)
    found = await chain(resolved, fetch, basis="auto", span=span, progress=progress or no_progress)
    if found is None:
        return None
    return StatementHistory(found.ref, merge(found.reports), {}, found.notes)
