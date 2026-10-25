"""Expected failures whose messages tell the model how to recover.

Services raise these exceptions; the error middleware turns them into MCP tool or resource
errors with the message intact. Messages never contain credentials or upstream body text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis.errors import DataSourceError, NotConfiguredError

if TYPE_CHECKING:
    from opendart_analysis.errors import AnalysisError

API_KEY_MISSING = "The OpenDART API key is not configured. Set OPENDART_API__API_KEY, or mount the key as /run/secrets/OPENDART_API__API_KEY, and restart the server."
QUOTA_EXHAUSTED = (
    "The OpenDART daily request quota for this API key is exhausted. Retry after 00:00 KST."
)
MAINTENANCE = "OpenDART is under maintenance (status 800). Retry later."
UNAVAILABLE = "OpenDART did not respond after one retry. Retry in a minute."


class ServerError(Exception):
    """Base for expected failures with a safe, actionable message."""


class ConfigurationError(ServerError):
    """The server lacks configuration that a component needs, such as the API key."""


class InvalidArgumentError(ServerError):
    """An argument passed schema validation but cannot be used; the message says why."""


class CompanyNotFoundError(InvalidArgumentError):
    """No company in the directory matches the requested name or code."""


class AmbiguousCompanyError(InvalidArgumentError):
    """Several companies match a name; the message lists candidates with their codes."""


class DirectoryUnavailableError(ServerError):
    """The company directory is still loading or failed to load."""


class UpstreamError(ServerError):
    """OpenDART failed, rejected the request, or answered unexpectedly."""


class QuotaExhaustedError(UpstreamError):
    """The API key's daily quota is exhausted; retrying before midnight KST cannot help."""


class StillRunningError(ServerError):
    """Slow work outlived the caller's deadline; it continues and a retry finds it cached."""


def from_analysis(error: AnalysisError) -> ServerError:
    """Translate a structured analysis failure into the server error for its category.

    Analysis messages are safe and name no tools, so they pass through unchanged. Adapters
    that owe the model more specific instructions catch the analysis subclass themselves and
    build their own message from its attributes before falling back to this.

    Args:
        error (AnalysisError): Failure raised by an analysis workflow.

    Returns:
        ServerError: ``UpstreamError`` for a failed data source, ``ConfigurationError`` for
            a missing dependency, and ``InvalidArgumentError`` otherwise, including missing
            data; each keeps the analysis message.
    """
    message = str(error)
    if isinstance(error, DataSourceError):
        return UpstreamError(message)
    if isinstance(error, NotConfiguredError):
        return ConfigurationError(message)
    return InvalidArgumentError(message)
