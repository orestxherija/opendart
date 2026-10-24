"""Stakes in other companies at book value, from the periodic report.

OpenDART's investments-in-other-corporations table (``otr_cpr_invstmnt_sttus``) lists each
investee with opening and closing shares, ownership, and book value, the period's
acquisitions, disposals, and valuation changes, and the investee's latest total assets and
profit, followed by a total row. Investee names and purposes stay as filed (often Korean),
except for the common purposes, which are translated. Amounts are won as filed.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date, parse_percent
from opendart_analysis.financials.accounts import normalize
from opendart_analysis.financials.chain import no_progress
from opendart_analysis.financials.statements import prior_year_end, shift
from opendart_analysis.reports import first_available, period_volatility
from opendart_analysis.reports.query import ReportQuery

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.financials.chain import Progress
    from opendart_analysis.reports import FiscalCompany, ResolvedPeriod
    from opendart_analysis.upstream import Volatility

_TOTALS: Final = frozenset({"total", "합계", "총계", "계"})
_SUBTOTALS: Final = frozenset({"subtotal", "소계"})
_PURPOSES: Final = MappingProxyType(
    {
        "경영참여": "management participation",
        "단순투자": "simple investment",
        "일반투자": "general investment",
    }
)


class InvestmentRecord(Protocol):
    """The fields of one investee row that analysis reads."""

    @property
    def inv_prm(self) -> str | None:
        """Investee name as filed, or a total or subtotal label."""
        ...

    @property
    def invstmnt_purps(self) -> str | None:
        """Investment purpose as filed."""
        ...

    @property
    def frst_acqs_de(self) -> str | None:
        """Date of the first acquisition."""
        ...

    @property
    def bsis_blce_acntbk_amount(self) -> str | None:
        """Opening book value."""
        ...

    @property
    def incrs_dcrs_acqs_dsps_amount(self) -> str | None:
        """Book value acquired less disposed during the period."""
        ...

    @property
    def incrs_dcrs_evl_lstmn(self) -> str | None:
        """Valuation gain or loss during the period."""
        ...

    @property
    def trmend_blce_qy(self) -> str | None:
        """Shares held at the period end."""
        ...

    @property
    def trmend_blce_qota_rt(self) -> str | None:
        """Ownership at the period end, in percent."""
        ...

    @property
    def trmend_blce_acntbk_amount(self) -> str | None:
        """Book value at the period end."""
        ...

    @property
    def recent_bsns_year_fnnr_sttus_tot_assets(self) -> str | None:
        """Investee's total assets in its latest fiscal year."""
        ...

    @property
    def recent_bsns_year_fnnr_sttus_thstrm_ntpf(self) -> str | None:
        """Investee's net profit in its latest fiscal year."""
        ...

    @property
    def filing_number(self) -> str | None:
        """14-digit filing number of the periodic report."""
        ...


class FetchInvestments(Protocol):
    """Fetch one company's investments in other companies; bound by the caller."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[InvestmentRecord] | None:
        """Return the investee rows of a company's periodic report for one period.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[InvestmentRecord] | None: Rows, or None when the source has none.
        """
        ...


@dataclass(frozen=True, slots=True)
class Holding:
    """A stake in another company at book value; amounts in won.

    Attributes:
        name (str): Investee name as filed.
        purpose (str | None): Investment purpose, in English when common.
        ownership_pct (float | None): Ownership at the period end, in percent.
        shares (int | None): Shares held at the period end.
        book_value (int | None): Book value at the period end.
        first_acquired (date | None): Date of the first acquisition.
        opening_book_value (int | None): Book value at the prior fiscal year end.
        acquired_or_disposed (int | None): Book value acquired less disposed.
        valuation_change (int | None): Valuation gain or loss during the period.
        investee_total_assets (int | None): Investee's latest total assets.
        investee_net_income (int | None): Investee's latest net profit.
    """

    name: str
    purpose: str | None
    ownership_pct: float | None
    shares: int | None
    book_value: int | None
    first_acquired: date | None
    opening_book_value: int | None
    acquired_or_disposed: int | None
    valuation_change: int | None
    investee_total_assets: int | None
    investee_net_income: int | None


@dataclass(frozen=True, slots=True)
class Holdings:
    """A company's equity investments for one period.

    Attributes:
        ref (PeriodRef): Period of the report.
        investments (tuple[Holding, ...]): Holdings, largest book value first.
        total (Holding | None): The filing's total line, if any.
        filings (tuple[str, ...]): Filing numbers the rows come from.
    """

    ref: PeriodRef
    investments: tuple[Holding, ...]
    total: Holding | None
    filings: tuple[str, ...]


def _purpose(text: str | None) -> str | None:
    """Translate the common investment purposes, keeping others as filed.

    Args:
        text (str | None): Upstream purpose.

    Returns:
        str | None: Purpose in English when known.
    """
    cleaned = clean_text(text)
    return _PURPOSES.get("".join(cleaned.split()), cleaned) if cleaned else None


def holding(row: InvestmentRecord) -> Holding:
    """Normalize one investee row.

    Args:
        row (InvestmentRecord): Upstream row.

    Returns:
        Holding: Holding with amounts in won.
    """
    return Holding(
        name=clean_text(row.inv_prm) or "(unnamed)",
        purpose=_purpose(row.invstmnt_purps),
        ownership_pct=parse_percent(row.trmend_blce_qota_rt),
        shares=parse_amount(row.trmend_blce_qy),
        book_value=parse_amount(row.trmend_blce_acntbk_amount),
        first_acquired=parse_date(row.frst_acqs_de),
        opening_book_value=parse_amount(row.bsis_blce_acntbk_amount),
        acquired_or_disposed=parse_amount(row.incrs_dcrs_acqs_dsps_amount),
        valuation_change=parse_amount(row.incrs_dcrs_evl_lstmn),
        investee_total_assets=parse_amount(row.recent_bsns_year_fnnr_sttus_tot_assets),
        investee_net_income=parse_amount(row.recent_bsns_year_fnnr_sttus_thstrm_ntpf),
    )


def holdings_of(rows: Sequence[InvestmentRecord], ref: PeriodRef) -> Holdings | None:
    """Normalize a report's investee rows, separating the total and dropping subtotals.

    Args:
        rows (Sequence[InvestmentRecord]): Upstream rows in filing order.
        ref (PeriodRef): Period of the report.

    Returns:
        Holdings | None: Holdings, largest book value first, or None without rows.
    """
    if not rows:
        return None
    named = [(normalize(row.inv_prm or ""), holding(row)) for row in rows]
    totals = [item for name, item in named if name in _TOTALS]
    kept = [item for name, item in named if name not in _TOTALS | _SUBTOTALS]
    kept.sort(key=lambda item: item.book_value or 0, reverse=True)
    filings = tuple(dict.fromkeys(row.filing_number for row in rows if row.filing_number))
    return Holdings(ref, tuple(kept), totals[-1] if totals else None, filings)


async def fetch_holdings(
    company: FiscalCompany, ref: PeriodRef, *, fetch_investments: FetchInvestments, today: date
) -> Holdings | None:
    """Fetch and normalize a company's equity investments for one period, in one call.

    Args:
        company (FiscalCompany): Company.
        ref (PeriodRef): Period.
        fetch_investments (FetchInvestments): Investee rows; asked with ``period_volatility``.
        today (date): Today in KST, which sets the period's volatility.

    Returns:
        Holdings | None: Holdings, or None when the report has no investment table.
    """
    volatility = period_volatility(ref, fye_month=company.fye_month, today=today)
    rows = await fetch_investments(ReportQuery.of(company.corp_code, ref), volatility=volatility)
    return holdings_of(rows or (), ref)


async def latest_holdings(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    fetch_investments: FetchInvestments,
    today: date,
    progress: Progress | None = None,
) -> Holdings | None:
    """Find the newest candidate period with an investment table and read it.

    Probes at most three candidate periods, one call each.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        fetch_investments (FetchInvestments): Investee rows of one period.
        today (date): Today in KST, which sets each period's volatility.
        progress (Progress | None): Receives one message per period fetched.

    Returns:
        Holdings | None: Holdings of the newest period with a table, or None.
    """
    report = progress or no_progress

    async def fetch(ref: PeriodRef) -> Holdings | None:
        """Fetch one candidate period while reporting its progress.

        Args:
            ref (PeriodRef): Period to fetch.

        Returns:
            Holdings | None: Holdings, or None when the period has no table.
        """
        await report(f"Fetching {ref.label}")
        return await fetch_holdings(company, ref, fetch_investments=fetch_investments, today=today)

    found = await first_available(resolved, fetch)
    return None if found is None else found[1]


def opening_period(ref: PeriodRef) -> PeriodRef:
    """Return the period whose end the opening balances refer to.

    Args:
        ref (PeriodRef): Period of the report.

    Returns:
        PeriodRef: The prior fiscal year end.
    """
    return shift(ref, 1) if ref.period == "FY" else prior_year_end(ref)
