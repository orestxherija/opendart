"""Domain failures become MCP errors whose text reaches the model."""

from __future__ import annotations

import itertools
import logging

import pytest
from fastmcp import Client
from fastmcp.exceptions import PromptError, ResourceError, ToolError
from mcp import MCPError
from pydantic import BaseModel

from opendart_mcp.app.errors import (
    as_mcp_error,
    find_cause,
    prompt_errors,
    resource_errors,
)
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.errors import AmbiguousCompanyError, InvalidArgumentError, ServerError


class Profile(BaseModel):
    """A tool result for the conversion tests."""

    name: str


MESSAGE = "Ambiguous company 'Samsung'; candidates: 00126380 (005930), 00126362 (006400)."


@pytest.mark.parametrize("kind", [ToolError, ResourceError, PromptError])
def test_errors_keep_the_domain_message_and_log_quietly(kind):
    error = as_mcp_error(InvalidArgumentError("Use an ISO date."), kind)
    assert type(error) is kind
    assert str(error) == "Use an ISO date."
    assert error.log_level == logging.INFO


@pytest.mark.parametrize(
    ("decorator", "kind"), [(resource_errors, ResourceError), (prompt_errors, PromptError)]
)
@pytest.mark.anyio
async def test_decorators_convert_domain_failures(decorator, kind):
    @decorator
    async def failing(company: str) -> str:
        raise AmbiguousCompanyError(MESSAGE)

    with pytest.raises(kind, match="Ambiguous company") as raised:
        await failing("Samsung")
    assert isinstance(raised.value.__cause__, ServerError)
    assert failing.__name__ == "failing"


@pytest.mark.parametrize("decorator", [resource_errors, prompt_errors])
@pytest.mark.anyio
async def test_decorators_pass_results_and_other_failures_through(decorator):
    @decorator
    async def echo(value: str) -> str:
        if value == "boom":
            raise KeyError(value)
        return value

    assert await echo("ok") == "ok"
    with pytest.raises(KeyError, match="boom"):
        await echo("boom")


@pytest.mark.anyio
async def test_converted_failures_are_not_masked_without_the_middleware(wired):
    server = wired(middleware=False)

    @server.resource("test://company")
    @resource_errors
    async def company() -> str:
        raise AmbiguousCompanyError(MESSAGE)

    @server.prompt
    @prompt_errors
    async def brief() -> str:
        raise AmbiguousCompanyError(MESSAGE)

    @server.tool
    @markdown_view(lambda result: result.name)
    async def profile() -> Profile:
        raise AmbiguousCompanyError(MESSAGE)

    async with Client(server) as client:
        with pytest.raises(MCPError, match="Ambiguous company"):
            await client.read_resource("test://company")
        with pytest.raises(MCPError, match="Ambiguous company"):
            await client.get_prompt("brief", {})
        result = await client.call_tool("profile", {}, raise_on_error=False)
    assert result.content[0].text == MESSAGE


def chained(*errors):
    """Raise each error from the next, returning the outermost."""
    for outer, inner in itertools.pairwise(errors):
        outer.__cause__ = inner
    return errors[0]


def test_find_cause_follows_explicit_and_implicit_causes():
    domain = InvalidArgumentError("Use an ISO date.")
    assert find_cause(domain, ServerError) is domain
    assert (
        find_cause(chained(ToolError("masked"), RuntimeError("dependency"), domain), ServerError)
        is domain
    )
    implicit = KeyError("raised while handling the domain failure")
    implicit.__context__ = domain
    assert find_cause(implicit, ServerError) is domain
    assert find_cause(ToolError("plain"), ServerError) is None


def test_find_cause_looks_inside_exception_groups():
    domain = AmbiguousCompanyError(MESSAGE)
    group = ExceptionGroup("task group", [ValueError("other"), ExceptionGroup("inner", [domain])])
    assert find_cause(chained(ToolError("masked"), group), ServerError) is domain
    assert find_cause(ExceptionGroup("none", [ValueError("x")]), ServerError) is None


def test_find_cause_stops_on_cycles():
    first, second = ValueError("first"), KeyError("second")
    first.__cause__, second.__cause__ = second, first
    assert find_cause(first, ServerError) is None
