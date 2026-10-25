"""Synthetic periodic-report records and a recording data source for capital and ownership tests.

``Row`` carries the OpenDART SDK's field names and reads any field it was not given as None,
as the SDK's models do for fields a filing omits; ``Source`` answers queries from a table and
records each query with its volatility. Every number here is synthetic unless noted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

TODAY = dt.date(2026, 10, 22)
ANNUAL, HALF = "20260310002820", "20260814001234"
COUNTS = ("isu_stock_totqy", "now_to_isu_stock_totqy", "now_to_dcrs_stock_totqy", "redc")
COUNTS += ("profit_incnr", "rdmstk_repy", "etc", "istc_totqy", "tesstk_co", "distb_stock_co")


class Row:
    """A record with SDK field names; fields it was not given read as None."""

    def __init__(self, **fields: str | None) -> None:
        self.__dict__.update(fields)

    def __getattr__(self, name: str) -> None:
        if name.startswith("__"):
            raise AttributeError(name)

    def __repr__(self) -> str:
        return f"Row({self.__dict__!r})"


@dataclass(frozen=True)
class Company:
    corp_code: str = "00126380"
    fye_month: int = 12


def share_row(se: str, *values: str, number: str = ANNUAL) -> Row:
    """A share-count row: class, then the ten count columns in ``COUNTS`` order."""
    return Row(
        se=se, filing_number=number, stlm_dt="2025-12-31", **dict(zip(COUNTS, values, strict=True))
    )


@dataclass
class Source:
    """Answers ``(fiscal_year, report_code)`` or a corp code from a table; records queries."""

    table: dict[Any, list[Row]] = field(default_factory=dict)
    queries: list[tuple[Any, str]] = field(default_factory=list)

    async def __call__(self, query: Any, /, *, volatility: str) -> list[Row] | None:
        self.queries.append((query, volatility))
        key = getattr(query, "fiscal_year", None), getattr(query, "report_code", None)
        rows = self.table.get(key, self.table.get(None))
        return list(rows) if rows else None
