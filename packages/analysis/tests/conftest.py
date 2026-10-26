"""Shared analysis test fixtures, free of the SDK, the MCP server, and HTTP clients.

pytest-socket's ``--disable-socket`` (from ``pytest.toml``) keeps the suite offline.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous tests on asyncio, which ``DocumentStore`` requires."""
    return "asyncio"
