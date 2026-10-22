"""Vendor-neutral timing around a logical database operation, including commit.

Suggested module: app.db_observability. Wrap the transaction context INSIDE this
context. A normal `with` is also usable around async work. The operation name
must be a static bounded label (for example customer.update), never user input.
This records operation latency, not isolated query time or connection pool wait.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Literal


@dataclass(frozen=True)
class OperationMetric:
    name: str
    duration_seconds: float
    outcome: Literal["success", "error"]


@contextmanager
def observe_operation(
    operation_name: str,
    emit: Callable[[OperationMetric], None],
) -> Iterator[None]:
    """Emit only safe fields; exporter failures cannot replace a DB outcome."""
    started = monotonic()
    outcome: Literal["success", "error"] = "error"
    try:
        yield
        outcome = "success"
    finally:
        metric = OperationMetric(operation_name, monotonic() - started, outcome)
        try:
            emit(metric)
        except Exception:
            # Applications may count exporter failures separately, with no raw
            # exception/traceback: exporters may include connection secrets.
            pass
