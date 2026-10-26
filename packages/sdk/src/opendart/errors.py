"""Stable SDK failures, with messages that exclude credentials and response bodies."""

from __future__ import annotations


class OpenDARTError(Exception):
    """Base SDK failure with safe, structured operation context.

    Subclasses inherit the same constructor and context attributes.

    Attributes:
        operation (str): Endpoint path identifying the failed operation.
        http_status (int | None): HTTP status when relevant, otherwise None.
        status (str | None): OpenDART application status when present, otherwise None.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        http_status: int | None = None,
        status: str | None = None,
    ) -> None:
        """Initialize a failure without including credentials or upstream body text.

        Args:
            message (str): Safe diagnostic text for the exception message.
            operation (str): Endpoint path identifying the failed operation.
            http_status (int | None): Relevant HTTP status. Defaults to None.
            status (str | None): Relevant application status code. Defaults to None.
        """
        super().__init__(message)
        self.operation = operation
        self.http_status = http_status
        self.status = status


class UnavailableError(OpenDARTError):
    """No usable answer: transport failure, HTTP 429/5xx, or API maintenance/quota."""


class RejectedError(OpenDARTError):
    """The upstream rejected the parameters, credentials, or permissions."""


class ContractError(OpenDARTError):
    """The upstream returned an unexpected status, encoding, or response shape."""


class APIError(OpenDARTError):
    """A non-success application status, including unknown future three-digit codes."""


class NoDataError(APIError):
    """Status 013: the query returned no data."""


class FileUnavailableError(APIError):
    """Status 014: the requested file is unavailable."""


class QuotaExceededError(APIError, UnavailableError):
    """Status 020: the key's configured quota is exhausted."""


class ServiceUnavailableError(APIError, UnavailableError):
    """Status 800: upstream maintenance."""


class APIRejectedError(APIError, RejectedError):
    """An application-level parameter, credential, or permission rejection."""


class ResponseTooLargeError(ContractError):
    """The configured response byte budget was exceeded."""
