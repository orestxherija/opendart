"""dividend_history: probing, chaining earlier annual reports, notes, provenance, and bounds."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from opendart_analysis.dividends import YIELD_NOTE, dividend_history
from opendart_analysis.reports import PeriodRef, PeriodicReport, PeriodicTitle, ResolvedPeriod

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
ANNUAL = "20260310002820"
OLDER = "20230310000999"


@dataclass(frozen=True)
class Company:
    corp_code: str
    fye_month: int


SAMSUNG = Company("00126380", 12)


def row(label: str, stock: str, values: tuple[str, str, str], number: str = ANNUAL) -> object:
    current, prior, older = values
    return SimpleNamespace(
        filing_number=number, se=label, stock_knd=stock, thstrm=current, frmtrm=prior, lwfr=older
    )


def table(number: str = ANNUAL) -> list[object]:
    return [
        row("Par value per share (KRW)", "-", ("100", "100", "100"), number),
        row("Total cash dividends (KRW million)", "-", ("11,000", "9,800", "9,700"), number),
        row("Cash dividend rate of return (%)", "보통주", ("1.50", "2.70", "1.90"), number),
        row("Cash dividend per share (KRW)", "보통주", ("1,668", "1,446", "1,444"), number),
    ]


class Source:
    """A FetchService over filed tables keyed by fiscal year, recording each call."""

    def __init__(self, filed: dict[str, list[object]], fail: str | None = None) -> None:
        self.filed = filed
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self, service: str, /, *, volatility: str, **params: str | None
    ) -> object | None:
        self.calls.append({"service": service, "volatility": volatility, **params})
        if params["fiscal_year"] == self.fail:
            raise RuntimeError("quota")
        rows = self.filed.get(str(params["fiscal_year"]))
        return None if rows is None else SimpleNamespace(list=rows)


def annual(fiscal_year: int = 2025) -> ResolvedPeriod:
    report = PeriodicReport(
        ref=PeriodRef(fiscal_year, "FY"),
        parsed=PeriodicTitle("annual", fiscal_year, 12, None),
        filing_number=ANNUAL,
        title=f"Annual Report ({fiscal_year}.12)",
        filed=dt.date(fiscal_year + 1, 3, 10),
    )
    return ResolvedPeriod((PeriodRef(fiscal_year, "FY"),), report, None)


async def test_three_years_come_from_one_annual_report():
    source = Source({"2025": table()})
    history = await dividend_history(SAMSUNG, annual(), fetch_service=source, today=TODAY)
    assert history is not None
    assert history.ref == PeriodRef(2025, "FY")
    assert history.fiscal_years == (2025, 2024, 2023)
    by_measure = {row.measure: row for row in history.rows}
    assert list(by_measure) == ["cash_dps", "cash_dividends", "cash_yield", "par_value"]
    assert by_measure["cash_dividends"].values == {
        2025: 11_000_000_000,
        2024: 9_800_000_000,
        2023: 9_700_000_000,
    }
    assert by_measure["cash_yield"].values[2024] == 2.7
    assert [(s.filing_number, s.title) for s in history.sources] == [
        (ANNUAL, "Annual Report (2025.12)")
    ]
    assert history.notes == (YIELD_NOTE,)
    assert source.calls == [
        {
            "service": "alot_matter",
            "volatility": "low",
            "corporation_code": "00126380",
            "fiscal_year": "2025",
            "report_period": "11011",
        }
    ]


async def test_longer_histories_chain_every_third_annual_report():
    source = Source({"2025": table(), "2022": table(OLDER)})
    history = await dividend_history(SAMSUNG, annual(), years=7, fetch_service=source, today=TODAY)
    assert history is not None
    assert [call["fiscal_year"] for call in source.calls] == ["2025", "2022", "2019"]
    assert history.fiscal_years == (2025, 2024, 2023, 2022, 2021, 2020)
    assert history.missing == (PeriodRef(2019, "FY"),)
    assert history.notes == (
        "No dividend table for FY2019; earlier years are missing.",
        YIELD_NOTE,
    )
    dps = next(row for row in history.rows if row.measure == "cash_dps")
    assert dps.values[2023] == 1444
    assert [s.filing_number for s in history.sources] == [ANNUAL, OLDER]


async def test_no_table_in_any_candidate_is_none():
    source = Source({})
    assert await dividend_history(SAMSUNG, annual(), fetch_service=source, today=TODAY) is None
    assert len(source.calls) == 1


async def test_rows_without_yields_have_no_yield_note():
    rows = [row("Cash dividend per share (KRW)", "보통주", ("500", "-", "-"))]
    history = await dividend_history(
        SAMSUNG, annual(), fetch_service=Source({"2025": rows}), today=TODAY
    )
    assert history is not None
    assert (history.notes, history.fiscal_years) == ((), (2025,))


async def test_failures_of_data_access_propagate_unchanged():
    source = Source({"2025": table()}, fail="2022")
    with pytest.raises(RuntimeError, match="quota"):
        await dividend_history(SAMSUNG, annual(), years=4, fetch_service=source, today=TODAY)


@pytest.mark.parametrize("years", [0, 11])
async def test_years_are_bounded(years):
    with pytest.raises(ValueError, match="between 1 and 10"):
        await dividend_history(
            SAMSUNG, annual(), years=years, fetch_service=Source({}), today=TODAY
        )


async def test_only_annual_periods_are_read():
    resolved = ResolvedPeriod((PeriodRef(2026, "H1"),), None, None)
    source = Source({})
    with pytest.raises(ValueError, match='period="FY"'):
        await dividend_history(SAMSUNG, resolved, fetch_service=source, today=TODAY)
    assert source.calls == []
