"""Keep the OpenDART API key out of logs.

OpenDART takes the API key as the ``crtfc_key`` query parameter, and the HTTP client logs
every request URL at INFO. The SDK owns the redaction (``opendart.redaction``) and protects
its own HTTP client loggers when a client is created; this module re-exports it and extends
the protection to the httpx and httpcore loggers that other libraries in the server use.
The server process also renders every record, tracebacks included, through a redacting
formatter (``app.logs.configure_logging``).
"""

from __future__ import annotations

from typing import Final

from opendart.redaction import (
    HTTP_LOGGERS as SDK_HTTP_LOGGERS,
    REDACTED,
    RedactSecrets,
    RedactingFormatter,
    protect_loggers,
    redact,
)

HTTP_LOGGERS: Final = ("httpx2", "httpcore2", "httpx", "httpcore")

__all__ = [
    "HTTP_LOGGERS",
    "REDACTED",
    "RedactSecrets",
    "RedactingFormatter",
    "protect_secrets",
    "redact",
]


def protect_secrets() -> None:
    """Redact the API key from HTTP client log records, once per process."""
    protect_loggers(SDK_HTTP_LOGGERS + HTTP_LOGGERS)
