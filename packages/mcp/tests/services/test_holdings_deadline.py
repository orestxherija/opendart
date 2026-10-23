"""Slow holding-report downloads return the snapshot first and finish in the cache."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import anyio
import pytest

from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.domain.dates import DateWindow
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.holdings import PENDING_NOTE, holding_activity

COMPANY = Company(
    ref=CompanyRef(name="Example Co.", corp_code="00126380"), fye_month=12, profile=None
)
WINDOW = DateWindow(dt.date(2026, 4, 25), dt.date(2026, 10, 22))
INSIDER = {
    "rcept_no": "20260901000111",
    "rcept_dt": "2026-09-01",
    "corp_code": "00126380",
    "corp_name": "Example",
    "repror": "홍길동",
    "isu_exctv_rgist_at": "Registered",
    "isu_exctv_ofcps": "사장",
    "isu_main_shrholdr": "-",
    "sp_stock_lmp_cnt": "1,000",
    "sp_stock_lmp_irds_cnt": "100",
    "sp_stock_lmp_rate": "0.01",
    "sp_stock_lmp_irds_rate": "0.00",
}


@pytest.mark.anyio
async def test_slow_lists_are_pending_then_served_from_the_cache(sdk, upstream):
    gate = anyio.Event()

    async def slow(request):
        await gate.wait()
        return upstream.rows(INSIDER)

    upstream.route("/elestock.json", slow)
    gateway = Gateway(sdk, cache=TTLCache(max_weight=1000), concurrency=4, retry_delay=0)
    state = SimpleNamespace(require_gateway=lambda: gateway)
    messages: list[str] = []

    async def progress(message):
        messages.append(message)

    first = await holding_activity(
        state, COMPANY, WINDOW, detailed=False, progress=progress, deadline=0.05
    )
    assert first.notes == [PENDING_NOTE]
    assert first.major_summary is None
    assert first.insider_summary is None

    gate.set()
    # The retry joins the download still in flight instead of starting another.
    second = await holding_activity(state, COMPANY, WINDOW, detailed=False, deadline=5)
    assert second.insider_summary is not None
    assert second.insider_summary.reports == 1
    assert upstream.count("/elestock.json") == 1
