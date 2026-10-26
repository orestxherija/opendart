"""Small FastMCP servers wired like the OpenDART server, for app-layer tests."""

from __future__ import annotations

import uuid

import pytest
from fastmcp import FastMCP
from fastmcp_tasks import TasksExtension

from opendart_mcp.app.middleware import ServerErrorMiddleware, UsageMiddleware
from opendart_mcp.core.metrics import Metrics


@pytest.fixture
def metrics():
    """Usage counters shared with the wired server's middleware."""
    return Metrics()


@pytest.fixture
def wired(metrics):
    """Build a server with masked errors and, by default, the usage and error middleware."""

    def build(*, middleware=True, tasks=False):
        stack = [UsageMiddleware(metrics), ServerErrorMiddleware()] if middleware else []
        server = FastMCP("Wiring", version="0.0.1", mask_error_details=True, middleware=stack)
        if tasks:
            queue = f"test-{uuid.uuid4().hex[:12]}"
            server.add_extension(TasksExtension(url="memory://", name=queue, concurrency=2))
        return server

    return build
