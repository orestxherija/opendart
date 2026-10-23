"""Output models for dividend history by share class and fiscal year."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from opendart_mcp.models.common import CompanyOutput, OutputModel

DividendMeasure = Literal[
    "cash_dps",
    "stock_dps",
    "cash_dividends",
    "stock_dividends",
    "payout_ratio",
    "cash_yield",
    "stock_yield",
    "net_income",
    "eps",
    "par_value",
    "other",
]
"""What a dividend row measures; ``other`` keeps rows the server does not recognize."""

ValueUnit = Literal["KRW", "KRW/share", "%", "shares/share"]
"""Unit of a row's values; totals are converted from the filed KRW million to won."""

EarningsBasis = Literal["consolidated", "separate"]
"""Statements a row's earnings figure comes from."""


class DividendRow(OutputModel):
    """One measure for one share class across fiscal years."""

    measure: DividendMeasure
    share_class: str | None = Field(
        default=None, description="common, preferred, or the class as filed; null for totals."
    )
    basis: EarningsBasis | None = None
    unit: ValueUnit
    values_by_year: dict[str, int | float] = Field(description="Fiscal year to value.")
    label: str | None = Field(default=None, description="Row label as filed.")


class DividendsResult(CompanyOutput):
    """Dividend history from annual reports."""

    fiscal_years: list[int] = Field(default_factory=list)
    rows: list[DividendRow] = Field(default_factory=list)
