"""Per-component usage metrics and per-request upstream call attribution.

The usage middleware opens a request scope; the gateway counts each upstream request in the
active scope, so every component call records how many OpenDART requests it caused.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(slots=True)
class CallScope:
    """Upstream requests made on behalf of one component call.

    Attributes:
        upstream (int): Requests sent to OpenDART, including retries.
    """

    upstream: int = 0


MAX_KEYS = 200
"""Distinct component keys kept; arbitrary URIs and names must not grow memory unboundedly."""

OVERFLOW_KEY = "other"
"""Key that collects calls beyond MAX_KEYS distinct keys."""

_SCOPE: ContextVar[CallScope | None] = ContextVar("opendart_mcp_call_scope", default=None)


def count_upstream() -> None:
    """Attribute one upstream request to the active component call, if any."""
    scope = _SCOPE.get()
    if scope is not None:
        scope.upstream += 1


def uncount_upstream() -> None:
    """Withdraw one attribution for a request that was never sent."""
    scope = _SCOPE.get()
    if scope is not None and scope.upstream > 0:
        scope.upstream -= 1


@contextmanager
def call_scope() -> Iterator[CallScope]:
    """Collect upstream requests made while the block runs.

    Yields:
        CallScope: Counter for the block; tasks started inside share it.
    """
    scope = CallScope()
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


@dataclass(slots=True)
class ComponentStats:
    """Counters for one tool, resource, or prompt.

    Attributes:
        calls (int): Completed calls, successful or not.
        errors (dict[str, int]): Failures by exception type name.
        total_ms (float): Summed duration in milliseconds.
        max_ms (float): Longest call in milliseconds.
        upstream (int): OpenDART requests caused by these calls.
    """

    calls: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    total_ms: float = 0.0
    max_ms: float = 0.0
    upstream: int = 0


@dataclass(slots=True)
class Metrics:
    """Usage counters keyed by component kind and name, for the status resource.

    Attributes:
        components (dict[str, ComponentStats]): Stats keyed like ``tool:find_company``.
    """

    components: dict[str, ComponentStats] = field(default_factory=dict)

    def record(
        self, key: str, *, elapsed_ms: float, upstream: int, error: str | None = None
    ) -> None:
        """Record one finished call.

        Args:
            key (str): Component key such as ``tool:find_company``.
            elapsed_ms (float): Call duration in milliseconds.
            upstream (int): OpenDART requests the call caused.
            error (str | None): Exception type name when the call failed.
        """
        if key not in self.components and len(self.components) >= MAX_KEYS:
            key = OVERFLOW_KEY
        stats = self.components.setdefault(key, ComponentStats())
        stats.calls += 1
        stats.total_ms += elapsed_ms
        stats.max_ms = max(stats.max_ms, elapsed_ms)
        stats.upstream += upstream
        if error is not None:
            stats.errors[error] = stats.errors.get(error, 0) + 1
