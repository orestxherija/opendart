"""Upstream gateway: caching, coalescing, retries, error translation, and usage."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import anyio
import httpx2
import pytest

from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.errors import (
    MAINTENANCE,
    QUOTA_EXHAUSTED,
    UNAVAILABLE,
    ConfigurationError,
    InvalidArgumentError,
    QuotaExhaustedError,
    UpstreamError,
)
from opendart_mcp.core.gateway import Gateway, Usage, cache_key
from opendart_mcp.core.ttl import DAY, FILINGS
from opendart_mcp.domain.dates import KST

SAMSUNG = "00126380"


@pytest.fixture
def gateway(sdk):
    return Gateway(sdk, cache=TTLCache(max_weight=100), concurrency=2, retry_delay=0)


def company(upstream):
    upstream.route("/company.json", upstream.ok(corp_name="삼성전자", corp_cls="Y"))


@pytest.mark.anyio
async def test_answers_are_cached_by_method_and_arguments(gateway, upstream):
    company(upstream)
    first = await gateway.call(60, gateway.sdk.disclosures.company, corporation_code=SAMSUNG)
    second = await gateway.call(60, gateway.sdk.disclosures.company, corporation_code=SAMSUNG)
    assert first is second
    assert first is not None
    assert first.corporation_name == "삼성전자"
    assert upstream.count("/company.json") == 1
    await gateway.call(0, gateway.sdk.disclosures.company, corporation_code="00164779")
    await gateway.call(0, gateway.sdk.disclosures.company, corporation_code="00164779")
    assert upstream.count("/company.json") == 3


@pytest.mark.anyio
async def test_no_data_is_an_empty_cached_answer(gateway, upstream):
    call = gateway.sdk.disclosures.company
    assert await gateway.call(60, call, corporation_code=SAMSUNG) is None
    assert await gateway.call(60, call, corporation_code=SAMSUNG) is None
    assert upstream.count() == 1


@pytest.mark.anyio
async def test_concurrent_identical_calls_share_one_request(gateway, upstream):
    gate = anyio.Event()

    async def slow(request):
        await gate.wait()
        return upstream.ok(corp_name="삼성전자")

    upstream.route("/company.json", slow)
    results = []

    async def call():
        results.append(
            await gateway.call(60, gateway.sdk.disclosures.company, corporation_code=SAMSUNG)
        )

    async with anyio.create_task_group() as tg:
        for _ in range(4):
            tg.start_soon(call)
        await anyio.wait_all_tasks_blocked()
        assert gateway.in_flight == 1
        gate.set()
    assert len({id(result) for result in results}) == 1
    assert upstream.count() == 1


@pytest.mark.anyio
async def test_transient_failure_is_retried_once(gateway, upstream):
    responses = iter([httpx2.Response(503), httpx2.Response(200, json=upstream.ok())])
    upstream.route("/company.json", lambda _: next(responses))
    assert await gateway.call(60, gateway.sdk.disclosures.company, corporation_code=SAMSUNG)
    assert gateway.usage.today == 2


@pytest.mark.anyio
async def test_repeated_failure_is_reported_after_one_retry(gateway, upstream):
    upstream.route("/company.json", lambda _: httpx2.Response(500))
    with pytest.raises(UpstreamError, match=UNAVAILABLE):
        await gateway.call(60, gateway.sdk.disclosures.company, corporation_code=SAMSUNG)
    assert upstream.count() == 2
    assert gateway.usage.failures == 1


@pytest.mark.parametrize(
    ("code", "kind", "message"),
    [
        ("020", QuotaExhaustedError, QUOTA_EXHAUSTED),
        ("800", UpstreamError, MAINTENANCE),
        ("010", ConfigurationError, "rejected the API key"),
        ("100", UpstreamError, "rejected the request to /company.json (status 100)"),
        ("900", UpstreamError, "could not answer /company.json (status 900)"),
    ],
)
@pytest.mark.anyio
async def test_application_statuses_are_translated_without_retry(
    gateway, upstream, code, kind, message
):
    upstream.route("/company.json", upstream.status(code))
    with pytest.raises(kind, match=re.escape(message)):
        await gateway.call(60, gateway.sdk.disclosures.company, corporation_code=SAMSUNG)
    assert upstream.count() == 1


@pytest.mark.anyio
async def test_invalid_arguments_never_reach_the_upstream(gateway, upstream):
    with pytest.raises(InvalidArgumentError, match="corporation_code"):
        await gateway.call(60, gateway.sdk.disclosures.company, corporation_code="123")
    assert upstream.count() == 0
    usage = gateway.usage
    assert (usage.today, usage.total, usage.failures, usage.by_operation) == (0, 0, 0, {})


@pytest.mark.anyio
async def test_concurrency_is_bounded(gateway, upstream):
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await anyio.sleep(0.01)
        active -= 1
        return upstream.ok()

    upstream.route("/company.json", handler)

    async def call(code):
        await gateway.call(60, gateway.sdk.disclosures.company, corporation_code=code)

    async with anyio.create_task_group() as tg:
        for n in range(6):
            tg.start_soon(call, f"{n:08d}")
    assert upstream.count() == 6
    assert peak == 2


def test_usage_resets_at_midnight_kst():
    usage = Usage()
    late = datetime(2026, 10, 22, 23, 59, tzinfo=KST)
    usage.record("company", late)
    usage.record("company", late)
    usage.record("search", late + timedelta(minutes=2))
    assert (usage.day, usage.today, usage.total) == ("2026-10-23", 1, 3)
    assert usage.by_operation == {"company": 2, "search": 1}


def test_cache_keys_ignore_keyword_order_and_freeze_lists(sdk):
    method = sdk.financial_statements.fnltt_multi_acnt
    one = cache_key(method, (), {"corporation_codes": ["1", "2"], "fiscal_year": "2025"})
    two = cache_key(method, (), {"fiscal_year": "2025", "corporation_codes": ["1", "2"]})
    assert one == two
    assert hash(one) == hash(two)


class Ticks:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.mark.anyio
async def test_no_data_is_rechecked_sooner_than_data(sdk, upstream):
    ticks = Ticks()
    gateway = Gateway(
        sdk, cache=TTLCache(max_weight=100, clock=ticks), concurrency=2, retry_delay=0
    )
    call = gateway.sdk.disclosures.company
    assert await gateway.call(DAY, call, corporation_code=SAMSUNG) is None
    ticks.now = FILINGS + 1
    company(upstream)
    assert await gateway.call(DAY, call, corporation_code=SAMSUNG) is not None
    ticks.now = FILINGS * 3
    await gateway.call(DAY, call, corporation_code=SAMSUNG)
    assert upstream.count("/company.json") == 2
