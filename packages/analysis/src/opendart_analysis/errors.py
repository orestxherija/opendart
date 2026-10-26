"""Failure categories shared by analysis workflows.

Each category keeps one kind of failure apart from the others, so a caller can decide what to
do without parsing messages:

- ``MissingDataError``: the request cannot have data, such as a period that has not ended.
- ``DataSourceError``: the caller's data access failed or answered unusably.
- ``NotConfiguredError``: a dependency the request needs was not supplied.

Capabilities raise specific subclasses that carry the request's details as attributes, such as
``opendart_analysis.reports.PeriodUnavailableError``. An empty answer from data access is not a
failure: it is ``None`` or an empty result. Messages are complete sentences that are safe to show
to a user or a model: they contain no credentials or upstream response text and never tell the
reader to call a particular tool or restart a server.

Analysis never catches, wraps, or retries exceptions raised by caller-supplied data access, so
the caller's own exceptions, such as an SDK error, reach the caller unchanged. Data access may
raise ``DataSourceError`` when the caller wants a single exception family.
"""

from __future__ import annotations


class AnalysisError(Exception):
    """Base for expected analysis failures, with a safe message and inspectable attributes."""


class MissingDataError(AnalysisError):
    """The request cannot have data, for example because it is outside the data's coverage."""


class DataSourceError(AnalysisError):
    """Caller-supplied data access failed, rejected the request, or answered unusably.

    Attributes:
        operation (str | None): Data access operation that failed, when known.
    """

    def __init__(self, message: str, *, operation: str | None = None) -> None:
        """Describe a failed data access operation.

        Args:
            message (str): Safe description of the failure.
            operation (str | None): Data access operation that failed, when known.
        """
        super().__init__(message)
        self.operation = operation


class NotConfiguredError(AnalysisError):
    """A dependency the request needs, such as a data source, was not supplied.

    Attributes:
        dependency (str): Name of the missing dependency, such as ``search_filings``.
    """

    def __init__(self, message: str, *, dependency: str) -> None:
        """Describe a missing dependency.

        Args:
            message (str): Safe description of what is missing.
            dependency (str): Name of the missing dependency.
        """
        super().__init__(message)
        self.dependency = dependency
