"""Output models for get_capital_structure: shares, treasury stock, capital changes, proceeds.

Share counts are integers; per-share prices are integers in won; amounts raised are integers
in won. Share classes read ``common``, ``preferred``, ``total`` (all classes), or the class
name as filed.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from opendart_mcp.domain.types import ConcretePeriod
from opendart_mcp.models.common import CompanyOutput, OutputModel

CapitalSection = Literal["shares", "treasury_stock", "capital_changes", "use_of_proceeds"]
"""Sections of get_capital_structure, in output order."""

Offering = Literal["public", "private"]
"""How the money was raised: a public offering or a private placement."""


class ShareClassRow(OutputModel):
    """Share counts of one class, or of all classes, at the period end."""

    share_class: str = Field(description="common, preferred, total, or the class name as filed.")
    authorized: int | None = None
    issued: int | None = Field(default=None, description="Issued shares, treasury included.")
    treasury: int | None = None
    outstanding: int | None = Field(default=None, description="Issued minus treasury shares.")
    issued_to_date: int | None = Field(default=None, description="All shares ever issued.")
    decreased_to_date: int | None = Field(default=None, description="All shares ever cancelled.")
    capital_reduction: int | None = None
    retired_from_profits: int | None = None
    redeemed: int | None = None
    other_decrease: int | None = None


class TreasuryMovement(OutputModel):
    """Treasury shares of one class: opening and closing balance and movements in the period."""

    share_class: str
    method: str | None = Field(default=None, description="Acquisition method, broadest first.")
    begin: int | None = None
    acquired: int | None = None
    disposed: int | None = None
    retired: int | None = None
    end: int | None = None
    note: str | None = None


class CapitalChange(OutputModel):
    """One share issuance or reduction."""

    date: dt.date | None = None
    kind: str | None = Field(default=None, description="Type as filed, usually Korean.")
    category: str | None = Field(default=None, description="English name of the type.")
    share_class: str | None = None
    shares: int | None = None
    par_value: int | None = None
    price: int | None = Field(default=None, description="Issue or reduction price per share.")


class ProceedsUse(OutputModel):
    """Planned versus actual use of money raised; amount_paid, plan, actual_status: pre-2018."""

    offering: Offering
    kind: str | None = Field(default=None, description="Security or method as filed.")
    series: str | None = None
    paid_on: dt.date | None = None
    planned_use: str | None = None
    planned_amount: int | None = None
    actual_use: str | None = None
    actual_amount: int | None = None
    difference_reason: str | None = None
    amount_paid: int | None = None
    plan: str | None = None
    actual_status: str | None = None


class CapitalStructureResult(CompanyOutput):
    """Share capital of one company from one periodic report; unrequested sections are absent."""

    fiscal_year: int | None = None
    period: ConcretePeriod | None = None
    period_end: dt.date | None = None
    sections: list[CapitalSection]
    shares: list[ShareClassRow] | None = None
    shares_note: str | None = None
    treasury_stock: list[TreasuryMovement] | None = None
    treasury_stock_by_method: list[TreasuryMovement] | None = None
    capital_changes: list[CapitalChange] | None = None
    use_of_proceeds: list[ProceedsUse] | None = None
