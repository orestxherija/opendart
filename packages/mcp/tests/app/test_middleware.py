"""Usage metrics, recovery of masked domain errors, and the middleware stack."""

from __future__ import annotations

import logging

import anyio
import mcp.types as mt
import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from fastmcp.tools import ToolResult
from mcp import MCPError

from opendart_mcp.app.middleware import (
    AccessLogMiddleware,
    ServerErrorMiddleware,
    UsageMiddleware,
    build_middleware,
    resource_key,
)
from opendart_mcp.app.schemas import CompactSchemaMiddleware
from opendart_mcp.core.errors import CompanyNotFoundError, ConfigurationError
from opendart_mcp.core.metrics import Metrics, count_upstream
from opendart_mcp.settings import HttpSettings, Settings

KEY_MESSAGE = "Set OPENDART_API__API_KEY and restart the server."


@pytest.mark.anyio
async def test_tool_calls_are_counted_timed_and_attributed(wired, metrics):
    server = wired()

    @server.tool
    async def fetch(times: int) -> int:
        for _ in range(times):
            count_upstream()
        return times

    async with Client(server) as client:
        await client.call_tool("fetch", {"times": 2})
        await client.call_tool("fetch", {"times": 3})
    stats = metrics.components["tool:fetch"]
    assert (stats.calls, stats.upstream, stats.errors) == (2, 5, {})
    assert 0 < stats.max_ms <= stats.total_ms


@pytest.mark.anyio
async def test_concurrent_calls_keep_their_own_upstream_counts(wired, metrics):
    server = wired()
    gate = anyio.Event()

    @server.tool
    async def slow() -> str:
        count_upstream()
        with anyio.fail_after(5):
            await gate.wait()
        count_upstream()
        return "slow"

    @server.tool
    async def quick() -> str:
        count_upstream()
        gate.set()
        return "quick"

    async with Client(server) as client, anyio.create_task_group() as tasks:
        tasks.start_soon(client.call_tool, "slow", {})
        tasks.start_soon(client.call_tool, "quick", {})
    assert metrics.components["tool:slow"].upstream == 2
    assert metrics.components["tool:quick"].upstream == 1


@pytest.mark.anyio
async def test_failures_are_counted_by_their_cause(wired, metrics):
    server = wired()

    @server.tool
    async def explicit() -> str:
        raise ToolError("Not today.")

    @server.tool
    async def domain() -> str:
        raise CompanyNotFoundError("No company matches 'x'; call find_company.")

    @server.tool
    async def crash() -> str:
        raise ValueError("internal detail")

    async with Client(server) as client:
        for name in ("explicit", "domain", "crash"):
            assert (await client.call_tool(name, {}, raise_on_error=False)).is_error
    assert metrics.components["tool:explicit"].errors == {"ToolError": 1}
    assert metrics.components["tool:domain"].errors == {"CompanyNotFoundError": 1}
    assert metrics.components["tool:crash"].errors == {"ValueError": 1}


@pytest.mark.anyio
async def test_resources_are_grouped_by_shape_and_prompts_by_name(wired, metrics):
    server = wired()

    @server.resource("opendart://company/{corp_code}/filings{?since}")
    async def filings(corp_code: str, since: str = "90d") -> str:
        count_upstream()
        return f"{corp_code} {since}"

    @server.prompt
    def brief(company: str) -> str:
        return f"Brief {company}."

    async with Client(server) as client:
        await client.read_resource("opendart://company/00126380/filings?since=30d")
        await client.read_resource("opendart://company/00164779/filings")
        await client.get_prompt("brief", {"company": "Samsung"})
    stats = metrics.components["resource:opendart://company/{id}/filings"]
    assert (stats.calls, stats.upstream) == (2, 2)
    assert metrics.components["prompt:brief"].calls == 1


@pytest.mark.parametrize(
    ("uri", "key"),
    [
        ("opendart://company/00126380", "resource:opendart://company/{id}"),
        (
            "opendart://filing/20260814001234/sections/s3",
            "resource:opendart://filing/{id}/sections/{section}",
        ),
        (
            "opendart://company/00126380/filings?since=30d",
            "resource:opendart://company/{id}/filings",
        ),
        ("opendart://reference/vocabulary", "resource:opendart://reference/vocabulary"),
        ("ui://opendart/financials.v1.html", "resource:ui://opendart/financials.v1.html"),
    ],
)
def test_resource_keys_hide_identifiers(uri, key):
    assert resource_key(uri) == key


@pytest.mark.anyio
async def test_masked_domain_failures_regain_their_message(wired):
    server = wired()

    @server.tool
    async def tool_failure() -> str:
        raise ConfigurationError(KEY_MESSAGE)

    @server.resource("test://failure")
    async def resource_failure() -> str:
        raise ConfigurationError(KEY_MESSAGE)

    @server.prompt
    async def prompt_failure() -> str:
        raise ConfigurationError(KEY_MESSAGE)

    async with Client(server) as client:
        result = await client.call_tool("tool_failure", {}, raise_on_error=False)
        assert result.is_error
        assert result.content[0].text == KEY_MESSAGE
        with pytest.raises(MCPError, match=KEY_MESSAGE):
            await client.read_resource("test://failure")
        with pytest.raises(MCPError, match=KEY_MESSAGE):
            await client.get_prompt("prompt_failure", {})


@pytest.mark.anyio
async def test_without_the_middleware_domain_failures_stay_masked(wired):
    server = wired(middleware=False)

    @server.tool
    async def tool_failure() -> str:
        raise ConfigurationError(KEY_MESSAGE)

    async with Client(server) as client:
        result = await client.call_tool("tool_failure", {}, raise_on_error=False)
    assert result.content[0].text == "Error calling tool 'tool_failure'"


@pytest.mark.anyio
async def test_unexpected_failures_stay_masked_and_tool_errors_pass_through(wired):
    server = wired()

    @server.tool
    async def crash() -> str:
        raise ValueError("internal detail")

    @server.tool
    async def explicit() -> str:
        raise ToolError("Not today.")

    async with Client(server) as client:
        crashed = await client.call_tool("crash", {}, raise_on_error=False)
        refused = await client.call_tool("explicit", {}, raise_on_error=False)
    assert crashed.content[0].text == "Error calling tool 'crash'"
    assert refused.content[0].text == "Not today."


def missing_key(ctx: Context = CurrentContext()) -> str:
    raise ConfigurationError(KEY_MESSAGE)


@pytest.mark.anyio
async def test_a_domain_failure_in_a_dependency_regains_its_message(wired):
    server = wired()

    @server.tool
    async def needs_key(key: str = Depends(missing_key)) -> str:
        return key

    async with Client(server) as client:
        result = await client.call_tool("needs_key", {}, raise_on_error=False)
    assert result.content[0].text == KEY_MESSAGE


def test_the_stack_logs_limits_measures_and_recovers_in_that_order():
    metrics = Metrics()
    stack = build_middleware(Settings(http=HttpSettings(rate_limit=5.0, rate_burst=7)), metrics)
    assert [type(m) for m in stack] == [
        AccessLogMiddleware,
        RateLimitingMiddleware,
        CompactSchemaMiddleware,
        UsageMiddleware,
        ServerErrorMiddleware,
    ]
    access, limiter, _, usage, _ = stack
    assert access.logger.name == "opendart_mcp.access"
    assert access.methods == ["tools/call", "resources/read", "prompts/get"]
    assert (limiter.max_requests_per_second, limiter.burst_capacity) == (5.0, 7)
    assert limiter.global_limit is True
    assert usage._metrics is metrics


def test_rate_limiting_can_be_disabled():
    stack = build_middleware(Settings(http=HttpSettings(rate_limit=None)), Metrics())
    assert [type(m) for m in stack] == [
        AccessLogMiddleware,
        CompactSchemaMiddleware,
        UsageMiddleware,
        ServerErrorMiddleware,
    ]


@pytest.mark.anyio
async def test_in_process_calls_are_measured_too(wired, metrics):
    server = wired()

    @server.tool
    async def fetch() -> str:
        count_upstream()
        return "ok"

    await server.call_tool("fetch", {})
    assert (metrics.components["tool:fetch"].calls, metrics.components["tool:fetch"].upstream) == (
        1,
        1,
    )


@pytest.mark.anyio
async def test_calls_without_a_fastmcp_context_are_measured(metrics):
    async def call_next(context):
        count_upstream()
        return ToolResult(content="ok")

    params = mt.CallToolRequestParams(name="direct", arguments={})
    context = MiddlewareContext(message=params, fastmcp_context=None, method="tools/call")
    result = await UsageMiddleware(metrics).on_call_tool(context, call_next)
    assert result.content[0].text == "ok"
    assert (
        metrics.components["tool:direct"].calls,
        metrics.components["tool:direct"].upstream,
    ) == (1, 1)


@pytest.mark.anyio
async def test_expected_failures_are_logged_at_info(caplog):
    access = AccessLogMiddleware(logger=logging.getLogger("opendart_mcp.access.test"))
    server = FastMCP("Logged", middleware=[access], mask_error_details=True)

    @server.tool
    async def refuse() -> str:
        raise ToolError("Not today.", log_level=logging.INFO)

    @server.tool
    async def crash() -> str:
        raise ValueError("internal detail")

    caplog.set_level(logging.INFO, logger="opendart_mcp.access.test")
    async with Client(server) as client:
        await client.call_tool("refuse", {}, raise_on_error=False)
        await client.call_tool("crash", {}, raise_on_error=False)
    errors = [r for r in caplog.records if "_error" in r.getMessage()]
    assert [r.levelno for r in errors] == [logging.INFO, logging.ERROR]
    assert '"expected": 1' in errors[0].getMessage()
