"""Reading a company's events through caller-supplied data access, without the SDK or MCP."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass

import pytest

from opendart_analysis.catalog import EVENT_KINDS
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.errors import DataSourceError
from opendart_analysis.events import (
    AMENDED,
    POSSIBLY_AMENDED,
    EventQuery,
    ReadPolicy,
    amendment_flag,
    covered_window,
    describe,
    fetch_events,
    search_index,
)
from scripts.testing.events import convertible_bond, merger

pytestmark = pytest.mark.anyio

WINDOW = DateWindow(dt.date(2025, 10, 22), dt.date(2026, 10, 22))
CB = EVENT_KINDS["convertible_bond"].service
MERGER = EVENT_KINDS["merger"].service


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
    """Answers filing-index pages by disclosure group and records the queries."""

    def __init__(self, major=(), offerings=(), *, pages=1):
        self.groups = {"B": list(major), "C": list(offerings)}
        self.pages = pages
        self.queries = []

    async def __call__(self, query, /, *, volatility):
        assert volatility == "high"
        self.queries.append(query)
        rows = self.groups[query.group]
        return Page(rows, len(rows), self.pages) if rows else None


class Services:
    """Answers event services with decoded bodies and records the calls."""

    def __init__(self, bodies, failures=None):
        self.bodies = bodies
        self.failures = failures or {}
        self.calls = []
        self.in_flight = self.peak = 0

    async def __call__(self, service, /, *, volatility, **params):
        assert volatility == "medium"
        self.calls.append((service, params))
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        if service in self.failures:
            raise self.failures[service]
        rows = self.bodies.get(service)
        return {"status": "000", "list": rows} if rows else None


def unused_index():
    async def read(query, /, *, volatility):
        raise AssertionError(query)

    return read


async def test_the_filing_index_chooses_the_services_and_records_come_newest_first():
    index = Index(
        major=[
            Listed("20260915000123", "Decision on Issuance of Convertible Bonds"),
            Listed("20260901000456", "[Corrected description]Decision on Merger"),
            Listed("20260902000001", "Notice on Investor Relations"),
        ]
    )
    services = Services(
        {CB: [convertible_bond("20260915000123")], MERGER: [merger("20260901000456")]}
    )
    messages = []

    async def progress(message):
        messages.append(message)

    batch = await fetch_events(
        EventQuery("00126380", WINDOW, name="Samsung"),
        fetch_service=services,
        read_filing_page=index,
        progress=progress,
    )
    assert batch.strategy == "filing_index"
    assert set(batch.queried) == {"convertible_bond", "merger"}
    assert [r.filing_number for r in batch.records] == ["20260915000123", "20260901000456"]
    assert batch.with_data == batch.queried
    assert batch.failed == ()
    assert messages[0] == "Searching Samsung's major-issue and offering filings"
    assert [m[:24] for m in messages[1:]] == [
        "1/2 event reports read (",
        "2/2 event reports read (",
    ]
    assert {params["filing_start_date"] for _, params in services.calls} == {"20251022"}
    assert [(q.group, q.page, q.page_size) for q in index.queries] == [("B", 1, 100), ("C", 1, 100)]
    titles = batch.titles()
    flags = {r.kind: amendment_flag(describe(r), titles) for r in batch.records}
    assert flags == {"convertible_bond": None, "merger": AMENDED}
    assert [f.filing_number for f in batch.index.unstructured()] == ["20260902000001"]


async def test_an_incomplete_index_reads_every_kind_of_the_group():
    major = [Listed(f"2026091500{n:04d}", "Notice") for n in range(3)]
    index = Index(major=major, pages=5)
    services = Services({})
    batch = await fetch_events(
        EventQuery("00126380", WINDOW),
        fetch_service=services,
        read_filing_page=index,
        policy=ReadPolicy(max_index_pages=2),
    )
    assert batch.strategy == "all_kinds"
    assert batch.index.incomplete == frozenset({"B"})
    major_kinds = {k for k, spec in EVENT_KINDS.items() if spec.resource == "major_issues"}
    assert set(batch.queried) == major_kinds
    assert [q.page for q in index.queries if q.group == "B"] == [1, 2]


async def test_requested_kinds_skip_the_index_and_tolerated_failures_are_reported():
    services = Services(
        {CB: [convertible_bond()]}, failures={MERGER: DataSourceError("Unavailable.")}
    )
    batch = await fetch_events(
        EventQuery("00126380", WINDOW, kinds=("convertible_bond", "merger")),
        fetch_service=services,
        read_filing_page=unused_index(),
    )
    assert (batch.strategy, batch.index, batch.failed) == ("requested", None, ("merger",))
    assert batch.with_data == ("convertible_bond",)
    assert batch.titles() == {}


async def test_other_failures_propagate_unchanged():
    error = RuntimeError("quota")
    services = Services({}, failures={MERGER: error})
    with pytest.raises(RuntimeError) as raised:
        await fetch_events(
            EventQuery("00126380", WINDOW, kinds=("convertible_bond", "merger")),
            fetch_service=services,
            read_filing_page=unused_index(),
            policy=ReadPolicy(tolerate=lambda failure: isinstance(failure, DataSourceError)),
        )
    assert raised.value is error


async def test_concurrency_bounds_the_calls_in_flight():
    kinds = tuple(EVENT_KINDS)[:6]
    services = Services({})
    await fetch_events(
        EventQuery("00126380", WINDOW, kinds=kinds),
        fetch_service=services,
        read_filing_page=unused_index(),
        policy=ReadPolicy(concurrency=2),
    )
    assert len(services.calls) == 6
    assert services.peak <= 2


async def test_late_major_issue_decisions_are_possibly_amended():
    services = Services({CB: [convertible_bond("20261021000315", bddd="2026.09.15")]})
    batch = await fetch_events(
        EventQuery("00126380", WINDOW, kinds=("convertible_bond",)),
        fetch_service=services,
        read_filing_page=unused_index(),
    )
    (record,) = batch.records
    assert amendment_flag(describe(record), batch.titles()) == POSSIBLY_AMENDED


async def test_the_index_restricts_to_kinds_seen_and_allowed():
    index = Index(
        major=[
            Listed("20260915000123", "Decision on Issuance of Convertible Bonds"),
            Listed("20260901000456", "Decision on Merger"),
        ]
    )
    batch = await fetch_events(
        EventQuery("00126380", WINDOW, restrict=frozenset({"merger"})),
        fetch_service=Services({}),
        read_filing_page=index,
    )
    assert batch.queried == ("merger",)
    assert (await search_index("00126380", WINDOW, read_page=index)).complete


def test_windows_are_clipped_to_the_event_report_range():
    today = dt.date(2026, 10, 22)
    wide = DateWindow(dt.date(2010, 1, 1), dt.date(2027, 1, 1))
    assert covered_window(wide, today=today) == DateWindow(dt.date(2015, 1, 1), today)
    old = DateWindow(dt.date(2010, 1, 1), dt.date(2014, 12, 31))
    assert covered_window(old, today=today) is None


@pytest.mark.parametrize(
    "limits",
    [{"concurrency": 0}, {"concurrency": -1}, {"max_index_pages": 0}],
    ids=["no-concurrency", "negative-concurrency", "no-index-pages"],
)
def test_a_policy_rejects_limits_that_never_finish(limits):
    with pytest.raises(ValueError, match="at least 1"):
        ReadPolicy(**limits)


def test_a_policy_accepts_unbounded_and_single_call_reads():
    assert ReadPolicy(concurrency=None).concurrency is None
    assert (
        ReadPolicy(concurrency=1, max_index_pages=1).concurrency,
        ReadPolicy().max_index_pages,
    ) == (1, 3)
