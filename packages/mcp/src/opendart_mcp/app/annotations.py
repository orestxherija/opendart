"""Shared component annotations and execution settings."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from fastmcp.utilities.tasks import TaskConfig
from mcp.types import Annotations, ToolAnnotations

READ_ONLY: Final = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
"""Every tool only reads public filings; omitted hints would be treated pessimistically."""

TASK_OPTIONAL: Final = TaskConfig(mode="optional", poll_interval=timedelta(seconds=3))
"""Run as a background task for clients that support it, synchronously for the rest."""

FOR_ASSISTANT: Final = Annotations(audience=["assistant"], priority=0.5)
"""Reference context meant for the model rather than the user."""
