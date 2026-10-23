"""Output models for compare_companies: one row per company, one column per metric.

Amount columns hold integers in won (``unit`` "krw"); percentage columns hold floats
(``unit`` "pct"). The peer-table app reads ``columns``, ``rows``, ``missing``, and the echo
fields for its header.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from opendart_mcp.domain.types import Basis, ConcretePeriod, Unit
from opendart_mcp.models.common import CompanyRef, OutputModel, ToolOutput
from opendart_mcp.models.financials import Number, StatementBasis

CompareMetrics = Literal["key_accounts", "ratios", "both"]
"""Metric set requested from compare_companies."""

ColumnUnit = Literal["krw", "pct"]
"""Unit of a metric column's values."""


class MetricColumn(OutputModel):
    """A metric: one column of the peer table."""

    key: str
    label: str
    unit: ColumnUnit = Field(description="krw: integer won amounts; pct: percent.")


class PeerRow(OutputModel):
    """One company's values, aligned with the columns."""

    company: CompanyRef
    values: list[Number | None]
    basis_used: StatementBasis | None = Field(
        default=None, description="Statements used, when basis is auto."
    )


class MissingCompany(OutputModel):
    """A requested company left out of the table, and why."""

    company: str = Field(description="The input, or the resolved name when data is missing.")
    reason: str


class CompareResult(ToolOutput):
    """A peer table built from OpenDART's multi-company services."""

    company_count: int = Field(description="Companies with a row in the table.")
    fiscal_year: int | None = None
    period: ConcretePeriod | None = None
    basis: Basis
    unit: Unit = Field(description="Unit of the text table; structured amounts stay in won.")
    columns: list[MetricColumn]
    rows: list[PeerRow]
    missing: list[MissingCompany] = Field(default_factory=list)
