"""Choosing the latest preliminary-earnings release from synthetic fair disclosures.

Parsing is covered by ``tests/documents/test_preliminary.py``; here the parser is replaced by
a lookup from filing number to figures, so the tests exercise the search and the choice.
"""

from __future__ import annotations

from datetime import date

import pytest

from opendart_analysis.documents.preliminary import (
    PreliminaryChange,
    PreliminaryEarnings,
    PreliminaryPeriod,
    PreliminaryRow,
    PreliminaryValue,
)
from opendart_analysis.financials import (
    DisclosureQuery,
    latest_preliminary,
    preliminary as module,
    quarter_lines,
)
from packages.analysis.tests.financials.records import TODAY, Company, Filing, search

pytestmark = pytest.mark.anyio

SAMSUNG = Company("00126380")
CONSOLIDATED = "Report on Business Performance according to Consolidated Financial Statements (Fair Disclosure)"
SEPARATE = "Report on Business Performance (Fair Disclosure)"
GUIDANCE, COMPLETE, OLDER = "20261008800004", "20260930800010", "20260707800002"


def value(amount):
    return PreliminaryValue(krw=amount, raw=str(amount))


def row(metric, current, prior=None, year_ago=None, ytd=None, prior_ytd=None):
    change = PreliminaryChange(percent=None, raw="-")
    return PreliminaryRow(
        metric=metric,
        label_ko=metric,
        current_quarter=value(current),
        prior_quarter=value(prior),
        year_ago_quarter=value(year_ago),
        quarter_on_quarter=change,
        year_on_year=change,
        year_to_date=value(ytd),
        prior_year_to_date=value(prior_ytd),
        year_to_date_change=change,
    )


def release(number, end, *, complete):
    rows = [row("revenue", 80, 70, 75, 220, 200), row("operating_profit", 10, 8, 9)]
    if complete:
        rows.append(row("net_profit", 7, 6, 5))
    return PreliminaryEarnings(
        filing_number=number,
        basis="consolidated",
        periods=[PreliminaryPeriod(key="current_quarter", label_ko="당기실적", end=end)],
        rows=rows,
        is_amendment=False,
    )


class Opener:
    """Opens filings by number; a filing missing from the table cannot be opened."""

    def __init__(self, **documents):
        self.documents = documents
        self.opened = []

    async def __call__(self, filing_number, /):
        self.opened.append(filing_number)
        return self.documents.get(filing_number)


@pytest.fixture(autouse=True)
def parser(monkeypatch):
    def extract(parsed):
        return None if parsed == "not a template" else parsed

    monkeypatch.setattr(module, "extract_preliminary_earnings", extract)


async def test_a_complete_release_for_the_same_quarter_replaces_guidance():
    filings = search(
        Filing(GUIDANCE, CONSOLIDATED),
        Filing(COMPLETE, f"[Correction]{CONSOLIDATED}"),
        Filing("bad number", CONSOLIDATED),
        Filing("20261008800099", "Some other fair disclosure"),
    )
    opener = Opener(
        **{
            GUIDANCE: release(GUIDANCE, "2026-09-30", complete=False),
            COMPLETE: release(COMPLETE, "2026-09-30", complete=True),
        }
    )
    messages = []

    async def progress(message):
        messages.append(message)

    found = await latest_preliminary(
        SAMSUNG, search_disclosures=filings, open_filing=opener, today=TODAY, progress=progress
    )
    assert filings.calls == [
        (DisclosureQuery("00126380", date(2026, 6, 24), TODAY, "I002", 100), "high")
    ]
    assert opener.opened == [GUIDANCE, COMPLETE]
    assert messages == [
        f"Reading preliminary earnings in filing {GUIDANCE}",
        f"Reading preliminary earnings in filing {COMPLETE}",
    ]
    assert (found.filing_number, found.title) == (COMPLETE, f"[Correction]{CONSOLIDATED}")
    assert found.notes == (
        f"Filing {GUIDANCE} reports only revenue and operating profit; the complete release {COMPLETE} for the same quarter is used.",
    )


async def test_unreadable_disclosures_are_skipped_with_notes():
    filings = search(
        Filing(GUIDANCE, CONSOLIDATED),
        Filing("20261008800005", SEPARATE),
        Filing(COMPLETE, CONSOLIDATED),
    )
    opener = Opener(
        **{
            "20261008800005": "not a template",
            COMPLETE: release(COMPLETE, "2026-09-30", complete=True),
        }
    )
    found = await latest_preliminary(
        SAMSUNG, search_disclosures=filings, open_filing=opener, today=TODAY
    )
    # On the same day, consolidated results come before separate ones.
    assert opener.opened == [GUIDANCE, "20261008800005", COMPLETE]
    assert found.filing_number == COMPLETE
    assert found.notes == (
        f"Filing {GUIDANCE} ({CONSOLIDATED}) could not be opened, so it was skipped.",
        f"Filing 20261008800005 ({SEPARATE}) does not use the preliminary-results table.",
    )


async def test_guidance_stays_when_the_complete_release_is_another_quarter():
    filings = search(Filing(GUIDANCE, CONSOLIDATED), Filing(OLDER, CONSOLIDATED))
    opener = Opener(**{GUIDANCE: release(GUIDANCE, "2026-09-30", complete=False)})
    found = await latest_preliminary(
        SAMSUNG, search_disclosures=filings, open_filing=opener, today=TODAY
    )
    # The older disclosure was filed more than 60 days earlier, so it is not opened.
    assert opener.opened == [GUIDANCE]
    assert (found.filing_number, found.notes) == (GUIDANCE, ())


async def test_newer_guidance_stays_without_a_complete_release_for_its_quarter():
    filings = search(Filing(GUIDANCE, CONSOLIDATED), Filing(COMPLETE, CONSOLIDATED))
    opener = Opener(
        **{
            GUIDANCE: release(GUIDANCE, "2026-09-30", complete=False),
            COMPLETE: release(COMPLETE, "2026-09-30", complete=False),
        }
    )
    found = await latest_preliminary(
        SAMSUNG, search_disclosures=filings, open_filing=opener, today=TODAY
    )
    assert opener.opened == [GUIDANCE, COMPLETE]
    assert (found.filing_number, found.notes) == (GUIDANCE, ())


async def test_no_disclosure_is_none():
    opener = Opener()
    assert (
        await latest_preliminary(
            SAMSUNG, search_disclosures=search(), open_filing=opener, today=TODAY
        )
        is None
    )
    assert opener.opened == []


def test_quarter_lines_derive_growth_from_three_month_amounts():
    laid = quarter_lines(release(COMPLETE, "2026-09-30", complete=True), fye_month=12)
    assert [q.label for q in laid.quarters] == ["Q3 2026", "Q2 2026", "Q3 2025"]
    revenue = laid.lines[0]
    current, prior, year_ago = (q.ref for q in laid.quarters)
    assert revenue.values == {current: 80, prior: 70, year_ago: 75}
    assert revenue.cumulative == {current: 220, year_ago: 200, prior: None}
    assert laid.lines[1].cumulative == {}
    assert laid.derived == {
        "revenue_growth": 6.67,
        "operating_income_growth": 11.11,
        "net_income_growth": 40.0,
        "operating_margin": 12.5,
        "net_margin": 8.75,
        "revenue_qoq_growth": 14.29,
        "operating_income_qoq_growth": 25.0,
        "net_income_qoq_growth": 16.67,
    }
    assert laid.formula.startswith("derived: computed in code from the three-month amounts")
