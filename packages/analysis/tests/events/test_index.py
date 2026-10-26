"""The filing index: its disclosure groups, and reads that never outlive a failed search."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass

import pytest

from opendart_analysis.domain.categories import category_query
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.events.index import INDEX_GROUPS, search_index

pytestmark = pytest.mark.anyio

WINDOW = DateWindow(dt.date(2025, 10, 22), dt.date(2026, 10, 22))


@dataclass(frozen=True)
class Page:
    list: list[object]
    total_count: int | None = None
    total_page: int | None = None


class FailingIndex:
    """Fails one page read at once while the other reads are still waiting on the source."""

    def __init__(self, failing: tuple[str, int], *, pages: int) -> None:
        self.failing = failing
        self.pages = pages
        self.finished: list[tuple[str, int]] = []

    async def __call__(self, query, /, *, volatility):
        del volatility
        where = (query.group, query.page)
        if where == self.failing:
            message = f"page {query.page} of group {query.group} is unavailable"
            raise LookupError(message)
        await asyncio.sleep(0.01)
        self.finished.append(where)
        return Page([], total_page=self.pages)


def test_the_groups_are_the_major_issue_and_offering_categories():
    assert {category_query(name)[0] for name in ("major_issues", "offerings")} == set(INDEX_GROUPS)


@pytest.mark.parametrize(
    ("failing", "pages", "finished"),
    [
        (("B", 1), 1, [("C", 1)]),
        (("B", 2), 3, [("C", 1), ("B", 1), ("B", 3), ("C", 2), ("C", 3)]),
    ],
)
async def test_a_failed_page_read_leaves_no_read_running(failing, pages, finished):
    index = FailingIndex(failing, pages=pages)
    before = asyncio.all_tasks()
    with pytest.raises(LookupError, match="is unavailable"):
        await search_index("00126380", WINDOW, read_page=index)
    assert sorted(index.finished) == sorted(finished)
    assert asyncio.all_tasks() <= before
