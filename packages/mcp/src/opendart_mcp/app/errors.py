"""Convert expected domain failures into MCP errors whose text reaches the model.

FastMCP masks any other exception and logs it with a traceback, so expected failures are
converted inside each component, before FastMCP sees them, and logged quietly.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

from fastmcp.exceptions import PromptError, ResourceError, ToolError

from opendart_mcp.core.errors import ServerError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp.exceptions import FastMCPError


_MAX_DEPTH = 10


def find_cause[E: BaseException](failure: BaseException, kind: type[E], depth: int = 0) -> E | None:
    """Find an exception of a given type behind a failure.

    Follows explicit and implicit causes (FastMCP wraps failures, for example a dependency
    failure inside ``RuntimeError("Failed to resolve dependency")``) and looks inside
    exception groups, which task groups raise.

    Args:
        failure (BaseException): Raised exception.
        kind (type[E]): Exception type to look for.
        depth (int): Recursion depth, bounded to avoid cycles.

    Returns:
        E | None: The first matching exception, if any.
    """
    if depth > _MAX_DEPTH:
        return None
    if isinstance(failure, kind):
        return failure
    if isinstance(failure, BaseExceptionGroup):
        found = (find_cause(inner, kind, depth + 1) for inner in failure.exceptions)
        return next((item for item in found if item is not None), None)
    cause = failure.__cause__ or failure.__context__
    return None if cause is None else find_cause(cause, kind, depth + 1)


def as_mcp_error(error: ServerError, kind: type[FastMCPError]) -> FastMCPError:
    """Build an MCP error carrying a domain failure's message.

    Args:
        error (ServerError): Expected failure with an actionable message.
        kind (type[FastMCPError]): ToolError, ResourceError, or PromptError.

    Returns:
        FastMCPError: Error logged at INFO; its message is never masked.
    """
    return kind(str(error), log_level=logging.INFO)


def _converting[**P, R](
    kind: type[FastMCPError],
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Build a decorator that converts domain failures for one component kind.

    Args:
        kind (type[FastMCPError]): MCP error type to raise.

    Returns:
        Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]: Decorator.
    """

    def decorator(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        """Wrap one component function.

        Args:
            function (Callable[P, Awaitable[R]]): Resource or prompt implementation.

        Returns:
            Callable[P, Awaitable[R]]: Wrapper raising MCP errors.
        """

        @functools.wraps(function)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Run the component, converting expected failures.

            Args:
                *args (P.args): Positional arguments, passed through.
                **kwargs (P.kwargs): Keyword arguments, passed through.

            Returns:
                R: The component's result.

            Raises:
                FastMCPError: A domain failure, as an MCP error of the configured kind.
            """
            try:
                return await function(*args, **kwargs)
            except Exception as failure:
                error = find_cause(failure, ServerError)
                if error is None:
                    raise
                raise as_mcp_error(error, kind) from failure

        return wrapper

    return decorator


def resource_errors[**P, R](function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Convert domain failures in a resource function into resource errors.

    Args:
        function (Callable[P, Awaitable[R]]): Resource implementation.

    Returns:
        Callable[P, Awaitable[R]]: Wrapped function.
    """
    return _converting(ResourceError)(function)


def prompt_errors[**P, R](function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Convert domain failures in a prompt function into prompt errors.

    Args:
        function (Callable[P, Awaitable[R]]): Prompt implementation.

    Returns:
        Callable[P, Awaitable[R]]: Wrapped function.
    """
    return _converting(PromptError)(function)


def tool_errors[**P, R](function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Convert domain failures in a tool function into tool errors.

    ``markdown_view`` already applies this; use it for tools without a Markdown view.

    Args:
        function (Callable[P, Awaitable[R]]): Tool implementation.

    Returns:
        Callable[P, Awaitable[R]]: Wrapped function.
    """
    return _converting(ToolError)(function)
