"""Failures reported by the directory loader.

Messages are complete sentences that are safe to show to a user or a model: they never name
a tool or tell anyone to restart a server. Callers such as the MCP server build their own
instructions from the attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from opendart_analysis.errors import AnalysisError


@dataclass(frozen=True, slots=True)
class LoadFailure:
    """The most recent failed load attempt.

    Attributes:
        reason (str): Safe description: the ``describe_error`` result for a fetch failure,
            the ``DirectoryError`` message for an unusable archive, or ``unexpected <type>``.
        error (Exception): What the fetch callback, the archive parser, or the loader raised.
    """

    reason: str
    error: Exception


class DirectoryNotReadyError(AnalysisError):
    """No directory is loaded yet: it is still loading, or every attempt so far failed.

    Attributes:
        status (Literal["loading", "failed"]): Whether loading is in progress or failed.
        elapsed_s (float): Seconds since the loader started.
        failure (LoadFailure | None): The last failed attempt, when ``status`` is ``failed``.
    """

    def __init__(self, *, elapsed_s: float, failure: LoadFailure | None) -> None:
        """Describe why no directory is available.

        Args:
            elapsed_s (float): Seconds since the loader started.
            failure (LoadFailure | None): The last failed attempt, or None while loading.
        """
        if failure is None:
            message = f"The company directory is still loading ({int(elapsed_s)} s so far)."
        else:
            message = f"The company directory could not be loaded ({failure.reason})."
        super().__init__(message)
        self.status: Literal["loading", "failed"] = "loading" if failure is None else "failed"
        self.elapsed_s = elapsed_s
        self.failure = failure
