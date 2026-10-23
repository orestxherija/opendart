"""Output models for get_financials: line items by periods, derived metrics, and holdings.

Every view is a table: ``rows`` hold values aligned with ``periods``. Amounts are integers in
won; per-share amounts and percentages carry a ``kind`` and are never scaled. The financial
statements app reads ``view``, ``basis_used``, ``unit``, ``periods``, ``rows``, and ``notes``.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from opendart_mcp.domain.types import ConcretePeriod, Unit
from opendart_mcp.models.common import CompanyOutput, OutputModel

FinancialView = Literal[
    "summary",
    "income",
    "balance",
    "cash_flow",
    "comprehensive_income",
    "equity_changes",
    "ratios",
    "equity_investments",
    "preliminary",
]
"""Statement view requested from get_financials."""

StatementBasis = Literal["consolidated", "separate"]
"""Statements a result was built from."""

RowKind = Literal["per_share", "percent"]
"""Value kind of a row that is not an amount in won."""

# A plain alias rather than a type statement keeps the published schema free of $defs.
Number = int | float
"""A table value: integer won, or a float for percentages and fractional per-share amounts."""


class PeriodColumn(OutputModel):
    """A reporting period: one column of the table."""

    label: str
    end_date: date | None = None
    fiscal_year: int
    period: ConcretePeriod


class StatementRow(OutputModel):
    """A line item with values aligned to the periods."""

    account: str
    account_id: str | None = Field(default=None, description="XBRL account ID or indicator code.")
    kind: RowKind | None = Field(
        default=None, description="Unset: won amount; per_share: won per share; percent."
    )
    values: list[Number | None] = Field(
        description="One per period; quarterly income lines hold three-month amounts."
    )
    cumulative: list[int | None] | None = Field(
        default=None, description="Year-to-date amounts per period (quarterly income lines)."
    )


class EquityInvestment(OutputModel):
    """A stake in another company at book value, from the periodic report."""

    name: str
    purpose: str | None = None
    ownership_pct: float | None = None
    shares: int | None = None
    book_value: int | None = None
    first_acquired: date | None = None
    opening_book_value: int | None = None
    acquired_or_disposed: int | None = Field(
        default=None, description="Book value acquired less disposed during the period."
    )
    valuation_change: int | None = None
    investee_total_assets: int | None = None
    investee_net_income: int | None = None


class FinancialsResult(CompanyOutput):
    """Financial statement lines by period for one company."""

    view: FinancialView
    basis_used: StatementBasis | None = Field(
        default=None, description="Statements used; null where a basis does not apply."
    )
    unit: Unit = Field(description="Unit of the text table; structured amounts stay in won.")
    currency: str = "KRW"
    periods: list[PeriodColumn]
    rows: list[StatementRow]
    derived: dict[str, float] = Field(
        default_factory=dict, description="Computed in code, in percent; notes name the formulas."
    )
    investments: list[EquityInvestment] | None = None
