"""Return Markdown to the model and the typed result as structured content.

FastMCP derives ``outputSchema`` from the wrapped function's return annotation (it follows
``__wrapped__``), so the schema stays the model's while the text block becomes a compact
Markdown rendering. Structured content omits null fields: some hosts, Claude Code among
them, hand the structured JSON to the model instead of the text block.

The wrapper also installs the call's company chooser (elicitation on hosts that support it)
and turns a pending input request into the round's result.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from pydantic import BaseModel

from opendart_mcp.app.elicitation import InputRequiredError, company_chooser
from opendart_mcp.app.errors import as_mcp_error, find_cause
from opendart_mcp.app.middleware import measure, metrics_for
from opendart_mcp.core.errors import ServerError
from opendart_mcp.core.interaction import choosing

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp.types import InputRequiredResult


def structured(result: BaseModel) -> dict[str, object]:
    """Serialize a result for structured content.

    Args:
        result (BaseModel): Output model.

    Returns:
        dict[str, object]: JSON-compatible fields, without nulls.
    """
    return result.model_dump(mode="json", exclude_none=True)


type ViewResult = ToolResult | InputRequiredResult


async def _run[R](tool: object, ctx: object, call: Awaitable[R]) -> R:
    """Run a tool body, recording metrics when it runs as a background task.

    Background tasks run in a worker, outside the usage middleware, so the tool records its
    own call against the counters the middleware registered for the server.

    Args:
        tool (object): The wrapped tool function, whose FastMCP metadata names the tool.
        ctx (object): The call's injected ``ctx`` argument, if any.
        call (Awaitable[R]): The tool body.

    Returns:
        R: The body's result.
    """
    if not isinstance(ctx, Context) or not ctx.is_background_task:
        return await call
    metrics = metrics_for(ctx.fastmcp)
    if metrics is None:
        return await call
    name = getattr(getattr(tool, "__fastmcp__", None), "name", None) or getattr(
        tool, "__name__", "tool"
    )
    return await measure(metrics, f"tool:{name}", call)


def markdown_view[**P, R: BaseModel](
    render: Callable[[R], str],
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[ViewResult]]]:
    """Wrap a tool so its text content is ``render(result)``.

    Place it directly under the ``@tool(...)`` decorator.

    Args:
        render (Callable[[R], str]): Turns the result model into Markdown.

    Returns:
        Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[ViewResult]]]: Decorator.
    """

    def decorator(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[ViewResult]]:
        """Wrap one tool function.

        Args:
            function (Callable[P, Awaitable[R]]): Tool implementation returning a model.

        Returns:
            Callable[P, Awaitable[ViewResult]]: Wrapper returning text and structured content.
        """

        @functools.wraps(function)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ViewResult:
            """Run the tool and attach both views of its result.

            Args:
                *args (P.args): Positional arguments, passed through.
                **kwargs (P.kwargs): Keyword arguments, passed through.

            Returns:
                ViewResult: Markdown text and structured content, or a request for input.

            Raises:
                ToolError: A domain failure, with its actionable message.
            """
            ctx = kwargs.get("ctx")
            chooser = company_chooser(ctx, kwargs.get("state"))
            try:
                with choosing(chooser):
                    result = await _run(wrapper, ctx, function(*args, **kwargs))
            except Exception as failure:
                pending = find_cause(failure, InputRequiredError)
                if pending is not None:
                    return pending.result
                error = find_cause(failure, ServerError)
                if error is None:
                    raise
                raise as_mcp_error(error, ToolError) from failure
            return ToolResult(content=render(result), structured_content=structured(result))

        return wrapper

    return decorator
