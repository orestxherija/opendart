"""Assembling a calendar through caller-supplied data access, without the SDK or MCP."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest

from opendart_analysis.calendar import (
    CalendarItem,
    CalendarSubject,
    TooManyCompaniesError,
    calendar_window,
    corporate_action_calendar,
)
from opendart_analysis.catalog import EVENT_KINDS
from opendart_analysis.errors import DataSourceError
from opendart_analysis.events import ReadPolicy
from tests.support.events import HYNIX, SAMSUNG, buyback, convertible_bond, merger

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 22)
WINDOW = calendar_window("90d", today=TODAY)
CB = EVENT_KINDS["convertible_bond"].service
MERGER = EVENT_KINDS["merger"].service
BUYBACK = EVENT_KINDS["treasury_stock_acquisition"].service
SAMSUNG_CO = CalendarSubject(SAMSUNG[0], SAMSUNG[1], korean_name="삼성전자")
HYNIX_CO = CalendarSubject(HYNIX[0], HYNIX[1])


@dataclass(frozen=True)
class Listed:
    filing_number: str | None
    report_title: str | None


@dataclass(frozen=True)
class Page:
    list: list[Listed] | None
    total_count: int | None = None
    total_page: int | None = None


class Index:
    """Answers filing-index pages per company and disclosure group."""

    def __init__(self, filings):
        self.filings = filings
        self.queries = []

    async def __call__(self, query, /, *, volatility):
        assert volatility == "high"
        self.queries.append(query)
        rows = self.filings.get((query.corp_code, query.group), [])
        return Page(rows, len(rows), 1) if rows else None


class Services:
    """Answers event services per company and records the calls."""

    def __init__(self, bodies, failures=None):
        self.bodies = bodies
        self.failures = failures or {}
        self.calls = []

    async def __call__(self, service, /, *, volatility, **params):
        assert volatility == "medium"
        corp_code = params["corporation_code"]
        self.calls.append((service, corp_code, params["filing_start_date"]))
        if (service, corp_code) in self.failures:
            raise self.failures[service, corp_code]
        rows = self.bodies.get((service, corp_code))
        return {"status": "000", "list": rows} if rows else None


def watchlist():
    index = Index(
        {
            (SAMSUNG[0], "B"): [
                Listed("20260915000123", "Decision on Issuance of Convertible Bonds"),
                Listed("20260901000456", "Decision on Merger"),
                Listed("20240301000001", "Decision on Acquisition of Treasury Stock"),
            ],
            (HYNIX[0], "B"): [
                Listed("20261019000305", "Decision on Acquisition of Treasury Stock")
            ],
        }
    )
    services = Services(
        {
            (CB, SAMSUNG[0]): [convertible_bond()],
            (MERGER, SAMSUNG[0]): [merger()],
            (BUYBACK, HYNIX[0]): [buyback()],
        }
    )
    return index, services


@dataclass(frozen=True)
class Answer:
    items: tuple[CalendarItem, ...]
    note: str


def rows(calendar):
    return [(str(i.date), i.corp_code[-3:], i.action, i.source_kind) for i in calendar.items]


async def test_the_filing_index_picks_kinds_and_items_are_sorted():
    index, services = watchlist()
    messages = []

    async def progress(message):
        messages.append(message)

    calendar = await corporate_action_calendar(
        [SAMSUNG_CO, HYNIX_CO],
        window=WINDOW,
        fetch_service=services,
        read_filing_page=index,
        today=TODAY,
        progress=progress,
    )
    assert rows(calendar)[:4] == [
        ("2026-11-03", "380", "record_date", "merger"),
        ("2026-11-03", "380", "objection_start", "merger"),
        ("2026-11-12", "380", "subscription", "convertible_bond"),
        ("2026-11-12", "380", "payment_date", "convertible_bond"),
    ]
    assert rows(calendar)[-1] == ("2027-01-20", "779", "buyback_end", "treasury_stock_acquisition")
    assert [c.subject for c in calendar.companies] == [SAMSUNG_CO, HYNIX_CO]
    assert [m[:4] for m in messages] == ["1/2 ", "2/2 "]
    assert {m[4:] for m in messages} == {SAMSUNG[1], HYNIX[1]}
    # One index search per company and group, over the three-year window.
    assert {(q.corp_code, q.group, q.start) for q in index.queries} == {
        (code, group, dt.date(2023, 10, 22)) for code in (SAMSUNG[0], HYNIX[0]) for group in "BC"
    }
    # Bonds are read over three years, other kinds over one; the old buyback is not read.
    assert sorted(services.calls) == sorted(
        [
            (MERGER, SAMSUNG[0], "20251022"),
            (BUYBACK, HYNIX[0], "20251022"),
            (CB, SAMSUNG[0], "20231022"),
        ]
    )
    samsung = calendar.companies[0]
    assert [batch.window.start for batch in samsung.events] == [
        dt.date(2025, 10, 22),
        dt.date(2023, 10, 22),
    ]
    assert (samsung.failed, samsung.maturities, samsung.error) == ((), None, None)


async def test_requested_kinds_skip_the_index_and_empty_kinds_read_nothing():
    index, services = watchlist()
    calendar = await corporate_action_calendar(
        [SAMSUNG_CO],
        window=WINDOW,
        kinds=("merger",),
        fetch_service=services,
        read_filing_page=index,
        today=TODAY,
    )
    assert {i.source_kind for i in calendar.items} == {"merger"}
    assert index.queries == []
    nothing = await corporate_action_calendar(
        [SAMSUNG_CO],
        window=WINDOW,
        kinds=(),
        fetch_service=services,
        read_filing_page=index,
        today=TODAY,
    )
    assert (nothing.items, nothing.companies[0].events) == ((), ())
    assert len(services.calls) == 1


async def test_maturities_merge_within_the_window_and_keep_the_readers_answer():
    index, services = watchlist()
    asked = []

    async def maturities(subject, window):
        asked.append((subject.corp_code, window))
        inside = CalendarItem(
            dt.date(2026, 12, 22),
            subject.corp_code,
            "debt_maturity",
            "debt_securities",
            "20260814001234",
        )
        outside = CalendarItem(
            dt.date(2028, 1, 1),
            subject.corp_code,
            "debt_maturity",
            "debt_securities",
            "20260814001234",
        )
        return Answer((inside, outside), "covered")

    calendar = await corporate_action_calendar(
        [SAMSUNG_CO],
        window=WINDOW,
        kinds=("merger",),
        maturities=maturities,
        fetch_service=services,
        read_filing_page=index,
        today=TODAY,
    )
    assert asked == [(SAMSUNG[0], WINDOW)]
    same_day = [
        (i.action, i.source_kind) for i in calendar.items if i.date == dt.date(2026, 12, 22)
    ]
    assert same_day == [("effective_date", "merger"), ("debt_maturity", "debt_securities")]
    assert dt.date(2028, 1, 1) not in {i.date for i in calendar.items}
    assert calendar.companies[0].maturities.note == "covered"


async def test_a_tolerated_failure_leaves_one_company_without_items():
    index, services = watchlist()
    services.failures[BUYBACK, HYNIX[0]] = DataSourceError("down")
    failing = Index({**index.filings})

    async def read_page(query, /, *, volatility):
        if query.corp_code == SAMSUNG[0]:
            raise DataSourceError("index down")
        return await failing(query, volatility=volatility)

    calendar = await corporate_action_calendar(
        [SAMSUNG_CO, HYNIX_CO],
        window=WINDOW,
        fetch_service=services,
        read_filing_page=read_page,
        today=TODAY,
    )
    samsung, hynix = calendar.companies
    assert (samsung.items, str(samsung.error)) == ((), "index down")
    assert (hynix.failed, hynix.items, hynix.error) == (("treasury_stock_acquisition",), (), None)
    assert calendar.items == ()


async def test_other_failures_propagate():
    index, services = watchlist()
    services.failures[MERGER, SAMSUNG[0]] = RuntimeError("quota")
    with pytest.raises(RuntimeError, match="quota"):
        await corporate_action_calendar(
            [SAMSUNG_CO, HYNIX_CO],
            window=WINDOW,
            fetch_service=services,
            read_filing_page=index,
            today=TODAY,
        )
    strict = ReadPolicy(tolerate=lambda _: False)
    services.failures = {(BUYBACK, HYNIX[0]): DataSourceError("down")}
    with pytest.raises(DataSourceError):
        await corporate_action_calendar(
            [HYNIX_CO],
            window=WINDOW,
            fetch_service=services,
            read_filing_page=index,
            policy=strict,
            today=TODAY,
        )


async def test_companies_are_read_once_and_bounded():
    index, services = watchlist()
    calendar = await corporate_action_calendar(
        [HYNIX_CO, CalendarSubject(HYNIX[0], "duplicate")],
        window=WINDOW,
        fetch_service=services,
        read_filing_page=index,
        today=TODAY,
    )
    assert [c.subject for c in calendar.companies] == [HYNIX_CO]
    with pytest.raises(TooManyCompaniesError) as caught:
        await corporate_action_calendar(
            [SAMSUNG_CO, HYNIX_CO],
            window=WINDOW,
            fetch_service=services,
            read_filing_page=index,
            max_companies=1,
            today=TODAY,
        )
    assert (caught.value.count, caught.value.limit) == (2, 1)


async def test_a_failing_maturity_reader_fails_its_company_after_the_events():
    index, services = watchlist()

    async def maturities(subject, window):
        raise DataSourceError("debt down")

    calendar = await corporate_action_calendar(
        [HYNIX_CO],
        window=WINDOW,
        maturities=maturities,
        fetch_service=services,
        read_filing_page=index,
        today=TODAY,
    )
    (hynix,) = calendar.companies
    assert (hynix.items, str(hynix.error)) == ((), "debt down")
    assert services.calls == [(BUYBACK, HYNIX[0], "20251022")]
