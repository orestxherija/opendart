"""Server middleware: access logging, rate limiting, usage metrics, and error recovery.

Order matters: the first middleware is the outermost. Response caching is deliberately
absent: the gateway caches upstream answers for every component, including background
tasks, whose results FastMCP's caching middleware never stores.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any, override
from weakref import WeakKeyDictionary

from fastmcp.exceptions import FastMCPError, PromptError, ResourceError, ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from fastmcp.tools import ToolResult

from opendart_mcp.app.errors import as_mcp_error, find_cause
from opendart_mcp.app.schemas import CompactSchemaMiddleware
from opendart_mcp.core.errors import ServerError
from opendart_mcp.core.metrics import call_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import mcp.types as mt
    from fastmcp.prompts import PromptResult
    from fastmcp.resources import ResourceResult
    from fastmcp.server.middleware import CallNext, MiddlewareContext

    from opendart_mcp.core.metrics import Metrics
    from opendart_mcp.settings import Settings

_IDENTIFIERS = re.compile(r"\d{6,}")
_SECTION = re.compile(r"/sections/[^/]+")
UNKNOWN_TOOL = "tool:<unknown>"


def resource_key(uri: str) -> str:
    """Group resource reads by shape so codes and filing numbers share one counter.

    Args:
        uri (str): Requested resource URI.

    Returns:
        str: Key such as ``resource:opendart://company/{id}/filings``.
    """
    path = _SECTION.sub("/sections/{section}", uri.split("?", 1)[0])
    return "resource:" + _IDENTIFIERS.sub("{id}", path)


# Usage counters per server, so background task runs, which bypass the middleware, can
# record into the same counters.
_METRICS: WeakKeyDictionary[object, Metrics] = WeakKeyDictionary()


def failure_name(failure: BaseException) -> str:
    """Name a failure for metrics: the domain error type when there is one.

    Args:
        failure (BaseException): Raised exception.

    Returns:
        str: Exception type name.
    """
    return type(find_cause(failure, ServerError) or failure.__cause__ or failure).__name__


def metrics_for(server: object) -> Metrics | None:
    """Return the usage counters registered for a server.

    Args:
        server (object): FastMCP server.

    Returns:
        Metrics | None: Counters, once the usage middleware has seen a request.
    """
    return _METRICS.get(server)


def _always(result: object) -> bool:
    """Count every result.

    Args:
        result (object): Call result.

    Returns:
        bool: Always True.
    """
    del result
    return True


def _not_submission(result: object) -> bool:
    """Skip background-task submissions; the task records its own run.

    Args:
        result (object): Tool call result.

    Returns:
        bool: Whether the result is a finished tool result.
    """
    return isinstance(result, ToolResult)


async def measure[R](
    metrics: Metrics, key: str, call: Awaitable[R], *, counted: Callable[[R], bool] = _always
) -> R:
    """Time a component call and attribute its upstream requests and failures.

    Args:
        metrics (Metrics): Counters to record into.
        key (str): Component key such as ``tool:find_company``.
        call (Awaitable[R]): The work to measure.
        counted (Callable[[R], bool]): Whether a result counts as a finished call.

    Returns:
        R: The call's result.
    """
    start = time.perf_counter()
    with call_scope() as scope:
        try:
            result = await call
        except Exception as failure:
            elapsed = (time.perf_counter() - start) * 1000
            metrics.record(
                key, elapsed_ms=elapsed, upstream=scope.upstream, error=failure_name(failure)
            )
            raise
    if counted(result):
        elapsed = (time.perf_counter() - start) * 1000
        metrics.record(key, elapsed_ms=elapsed, upstream=scope.upstream)
    return result


class AccessLogMiddleware(StructuredLoggingMiddleware):
    """JSON access log that records expected failures at INFO instead of ERROR.

    Components raise expected failures (an ambiguous company, a missing key) as MCP errors
    with an INFO log level; the stock middleware logs every failure at ERROR.
    """

    @override
    def _create_error_message(
        self, context: MiddlewareContext[Any], start_time: float, error: Exception
    ) -> dict[str, str | int | float]:
        """Mark failures whose own log level is below ERROR.

        Args:
            context (MiddlewareContext[Any]): Request context.
            start_time (float): When the request started.
            error (Exception): The failure.

        Returns:
            dict[str, str | int | float]: Log fields.
        """
        message = super()._create_error_message(context, start_time, error)
        if getattr(error, "log_level", logging.ERROR) < logging.ERROR:
            message["expected"] = 1
        return message

    @override
    def _log_message(
        self, message: dict[str, str | int | float], log_level: int | None = None
    ) -> None:
        """Log expected failures at INFO.

        Args:
            message (dict[str, str | int | float]): Log fields.
            log_level (int | None): Requested level.
        """
        super()._log_message(message, logging.INFO if message.get("expected") else log_level)


class UsageMiddleware(Middleware):
    """Record calls, latency, failures, and upstream requests per component."""

    def __init__(self, metrics: Metrics) -> None:
        """Share counters with the status resource.

        Args:
            metrics (Metrics): Usage counters.
        """
        self._metrics = metrics

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Measure a tool call.

        Args:
            context (MiddlewareContext[mt.CallToolRequestParams]): Request context.
            call_next (CallNext[mt.CallToolRequestParams, ToolResult]): Rest of the chain.

        Returns:
            ToolResult: Tool result.
        """
        key = f"tool:{context.message.name}"
        if context.fastmcp_context is not None:
            server = context.fastmcp_context.fastmcp
            _METRICS[server] = self._metrics
            if await server.get_tool(context.message.name) is None:
                key = UNKNOWN_TOOL
        return await measure(self._metrics, key, call_next(context), counted=_not_submission)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Measure a resource read.

        Args:
            context (MiddlewareContext[mt.ReadResourceRequestParams]): Request context.
            call_next (CallNext[mt.ReadResourceRequestParams, ResourceResult]): Rest of the chain.

        Returns:
            ResourceResult: Resource contents.
        """
        return await measure(
            self._metrics, resource_key(str(context.message.uri)), call_next(context)
        )

    @override
    async def on_get_prompt(
        self,
        context: MiddlewareContext[mt.GetPromptRequestParams],
        call_next: CallNext[mt.GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        """Measure a prompt render.

        Args:
            context (MiddlewareContext[mt.GetPromptRequestParams]): Request context.
            call_next (CallNext[mt.GetPromptRequestParams, PromptResult]): Rest of the chain.

        Returns:
            PromptResult: Prompt messages.
        """
        return await measure(self._metrics, f"prompt:{context.message.name}", call_next(context))


class ServerErrorMiddleware(Middleware):
    """Restore actionable messages that FastMCP masked.

    Components convert domain failures themselves; this catches the rest, such as failures
    in dependencies, where FastMCP has replaced the message with a generic one.
    """

    @staticmethod
    async def _recover[R](call: Awaitable[R], kind: type[FastMCPError]) -> R:
        """Re-raise a masked domain failure with its own message.

        Args:
            call (Awaitable[R]): The rest of the middleware chain.
            kind (type[FastMCPError]): MCP error type for this component kind.

        Returns:
            R: The call's result.

        Raises:
            FastMCPError: The domain failure, unmasked.
        """
        try:
            return await call
        except FastMCPError as failure:
            cause = find_cause(failure, ServerError)
            if cause is not None and str(failure) != str(cause):
                raise as_mcp_error(cause, kind) from cause
            raise

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Unmask tool failures.

        Args:
            context (MiddlewareContext[mt.CallToolRequestParams]): Request context.
            call_next (CallNext[mt.CallToolRequestParams, ToolResult]): Rest of the chain.

        Returns:
            ToolResult: Tool result.
        """
        return await self._recover(call_next(context), ToolError)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Unmask resource failures.

        Args:
            context (MiddlewareContext[mt.ReadResourceRequestParams]): Request context.
            call_next (CallNext[mt.ReadResourceRequestParams, ResourceResult]): Rest of the chain.

        Returns:
            ResourceResult: Resource contents.
        """
        return await self._recover(call_next(context), ResourceError)

    @override
    async def on_get_prompt(
        self,
        context: MiddlewareContext[mt.GetPromptRequestParams],
        call_next: CallNext[mt.GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        """Unmask prompt failures.

        Args:
            context (MiddlewareContext[mt.GetPromptRequestParams]): Request context.
            call_next (CallNext[mt.GetPromptRequestParams, PromptResult]): Rest of the chain.

        Returns:
            PromptResult: Prompt messages.
        """
        return await self._recover(call_next(context), PromptError)


def build_middleware(settings: Settings, metrics: Metrics) -> list[Middleware]:
    """Assemble the middleware stack, outermost first.

    Args:
        settings (Settings): Server configuration.
        metrics (Metrics): Usage counters shared with the status resource.

    Returns:
        list[Middleware]: Middleware for the FastMCP constructor.
    """
    stack: list[Middleware] = [
        AccessLogMiddleware(
            logger=logging.getLogger("opendart_mcp.access"),
            methods=["tools/call", "resources/read", "prompts/get"],
        )
    ]
    if settings.http.rate_limit is not None:
        stack.append(
            RateLimitingMiddleware(
                max_requests_per_second=settings.http.rate_limit,
                burst_capacity=settings.http.rate_burst,
                global_limit=True,
            )
        )
    stack += [CompactSchemaMiddleware(), UsageMiddleware(metrics), ServerErrorMiddleware()]
    return stack
