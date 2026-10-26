"""Synthetic financial records and recording data sources for the financials tests.

``Row`` carries the OpenDART SDK's field names, so one class satisfies every statement record
Protocol; ``Source`` answers queries from a table and records each query with its volatility.
Every number here is synthetic.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, fields

TODAY = dt.date(2026, 10, 22)
ANNUAL, HALF, OLD_HALF = "20260310002820", "20260814003699", "20250814001111"
T = 10**12


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int = 12
    stock_code: str | None = None


@dataclass(frozen=True)
class Filing:
    filing_number: str | None
    report_title: str | None


@dataclass(frozen=True)
class Row:
    statement_type: str
    account_name: str
    current_period_amount: str | None = None
    prior_period_amount: str | None = None
    two_periods_prior_amount: str | None = None
    current_period_cumulative_amount: str | None = None
    prior_period_cumulative_amount: str | None = None
    filing_number: str | None = HALF
    currency: str | None = "KRW"
    statement_scope: str | None = "CFS"
    account_id: str | None = None
    account_detail: str | None = None
    frmtrm_q_amount: str | None = None
    stock_code: str | None = None


@dataclass(frozen=True)
class Indicator:
    idx_code: str | None
    indicator_name: str | None
    indicator_value: str | None
    corporation_code: str | None = "00126380"


def won(trillions: float | None) -> str | None:
    return None if trillions is None else f"{round(trillions * T):,}"


class Source:
    """A data-access callable that answers from a table keyed by a function of the query."""

    def __init__(self, answers, key):
        self.answers = answers
        self.key = key
        self.calls = []

    async def __call__(self, query, /, *, volatility):
        self.calls.append((query, volatility))
        return self.answers.get(self.key(query))


def by_period(query):
    return (query.fiscal_year, query.report_code)


def by_scope(query):
    return (query.fiscal_year, query.report_code, query.scope)


def by_category(query):
    return (query.fiscal_year, query.report_code, query.category)


def search(*filings):
    return Source({None: filings}, lambda _: None)


def values(record):
    return {f.name: getattr(record, f.name) for f in fields(record)}
