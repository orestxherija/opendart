"""Stakes in other companies at book value, from the periodic report (equity_investments).

``otr_cpr_invstmnt_sttus`` lists each investee with opening and closing shares, ownership,
and book value, the period's acquisitions, disposals, and valuation changes, and the
investee's latest total assets and profit, followed by a total row. Investee names and
purposes stay as filed (often Korean); the table puts the largest holdings first.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.normalize import clean_text, parse_amount, parse_date, parse_percent
from opendart_mcp.models.financials import EquityInvestment, StatementRow
from opendart_mcp.services.accounts import normalize
from opendart_mcp.services.periods import periodic_ttl
from opendart_mcp.services.statements import column, prior_year_end, shift

if TYPE_CHECKING:
    from opendart.models.periodic_reports import OtrCprInvstmntSttusResponseListItem
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.periods import PeriodRef
    from opendart_mcp.models.financials import PeriodColumn
    from opendart_mcp.services.companies import Company

CONCISE_HOLDINGS: Final = 20
"""Holdings a concise result lists, largest book value first."""

TOTAL_LABEL: Final = "Total (all investments)"
"""Row label of the filing's total line."""

_TOTALS: Final = frozenset({"total", "합계", "총계", "계"})
_SUBTOTALS: Final = frozenset({"subtotal", "소계"})
_PURPOSES: Final = MappingProxyType(
    {
        "경영참여": "management participation",
        "단순투자": "simple investment",
        "일반투자": "general investment",
    }
)
_DETAIL_FIELDS: Final = (
    "first_acquired",
    "opening_book_value",
    "acquired_or_disposed",
    "valuation_change",
    "investee_total_assets",
    "investee_net_income",
)


@dataclass(frozen=True, slots=True)
class Holdings:
    """A company's equity investments for one period.

    Attributes:
        ref (PeriodRef): Period of the report.
        investments (list[EquityInvestment]): Holdings, largest book value first.
        total (EquityInvestment | None): The filing's total line, if any.
        filings (list[str]): Filing numbers the rows come from.
    """

    ref: PeriodRef
    investments: list[EquityInvestment]
    total: EquityInvestment | None
    filings: list[str]


def _purpose(text: str | None) -> str | None:
    """Translate the common investment purposes, keeping others as filed.

    Args:
        text (str | None): Upstream purpose.

    Returns:
        str | None: Purpose in English when known.
    """
    cleaned = clean_text(text)
    return _PURPOSES.get("".join(cleaned.split()), cleaned) if cleaned else None


def _investment(row: OtrCprInvstmntSttusResponseListItem) -> EquityInvestment:
    """Normalize one investee row.

    Args:
        row (OtrCprInvstmntSttusResponseListItem): Upstream row.

    Returns:
        EquityInvestment: Holding with amounts in won.
    """
    return EquityInvestment(
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


async def fetch_holdings(state: AppState, company: Company, ref: PeriodRef) -> Holdings | None:
    """Fetch and normalize a company's equity investments for one period.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Period.

    Returns:
        Holdings | None: Holdings, or None when the report has no investment table.
    """
    gateway = state.require_gateway()
    response = await gateway.call(
        periodic_ttl(state, company, ref),
        gateway.sdk.periodic_reports.otr_cpr_invstmnt_sttus,
        corporation_code=company.corp_code,
        fiscal_year=str(ref.fiscal_year),
        report_period=ref.report_code,
    )
    rows: list[OtrCprInvstmntSttusResponseListItem] = (
        (response.list or []) if response is not None else []
    )
    if not rows:
        return None
    named = [(normalize(row.inv_prm or ""), _investment(row)) for row in rows]
    totals = [item for name, item in named if name in _TOTALS]
    holdings = [item for name, item in named if name not in _TOTALS | _SUBTOTALS]
    holdings.sort(key=lambda item: item.book_value or 0, reverse=True)
    filings = list(dict.fromkeys(row.filing_number for row in rows if row.filing_number))
    return Holdings(ref, holdings, totals[-1] if totals else None, filings)


def opening_period(ref: PeriodRef) -> PeriodRef:
    """Return the period whose end the opening balances refer to.

    Args:
        ref (PeriodRef): Period of the report.

    Returns:
        PeriodRef: The prior fiscal year end.
    """
    return shift(ref, 1) if ref.period == "FY" else prior_year_end(ref)


def _concise(item: EquityInvestment) -> EquityInvestment:
    """Drop the fields a concise result leaves out.

    Args:
        item (EquityInvestment): Holding.

    Returns:
        EquityInvestment: Holding with name, purpose, stake, shares, and book value.
    """
    return item.model_copy(update=dict.fromkeys(_DETAIL_FIELDS))


def _row(item: EquityInvestment, label: str | None = None) -> StatementRow:
    """Show a holding as a row of closing and opening book values.

    Args:
        item (EquityInvestment): Holding or total line.
        label (str | None): Row label; the holding's name by default.

    Returns:
        StatementRow: Row aligned with (closing, opening) periods.
    """
    return StatementRow(
        account=label or item.name, values=[item.book_value, item.opening_book_value]
    )


def holdings_table(
    holdings: Holdings, *, detailed: bool, fye_month: int
) -> tuple[list[PeriodColumn], list[StatementRow], list[EquityInvestment], str | None]:
    """Lay holdings out as book values by period plus a holdings list.

    Args:
        holdings (Holdings): Normalized holdings.
        detailed (bool): List every holding with every field.
        fye_month (int): Fiscal year-end month, for column end dates.

    Returns:
        tuple[list[PeriodColumn], list[StatementRow], list[EquityInvestment], str | None]:
            Columns (closing, opening), rows, holdings, and a note when holdings are hidden.
    """
    shown = holdings.investments if detailed else holdings.investments[:CONCISE_HOLDINGS]
    rows = [_row(item) for item in shown]
    if holdings.total is not None:
        rows.append(_row(holdings.total, TOTAL_LABEL))
    periods = [column(holdings.ref, fye_month=fye_month)]
    periods.append(column(opening_period(holdings.ref), fye_month=fye_month))
    hidden = len(holdings.investments) - len(shown)
    note = (
        f'Showing the {len(shown)} largest of {len(holdings.investments)} holdings by book value; pass response_format="detailed" for all of them.'
        if hidden
        else None
    )
    investments = shown if detailed else [_concise(item) for item in shown]
    return periods, rows, investments, note
