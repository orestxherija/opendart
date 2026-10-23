"""Server logging: redacted output, and expected errors without tracebacks.

Redaction of the API key lives in ``core.redaction``; ``configure_logging`` applies it to
the server process's root handlers. Components raise MCP errors for expected situations
(an ambiguous company, a missing key) at INFO level, but FastMCP logs resource and prompt
errors with their traceback whatever the level; ``QuietExpectedErrors`` drops the
traceback for records below ERROR.
"""

from __future__ import annotations

import logging
from typing import Final, override

from opendart_mcp.core.redaction import (
    HTTP_LOGGERS,
    RedactSecrets,
    RedactingFormatter,
    protect_secrets,
)

FASTMCP_SERVER_LOGGER: Final = "fastmcp.server.server"
QUIET_LOGGERS: Final = ("docket.worker",)
"""Loggers kept at WARNING besides the HTTP clients: the task worker logs every task-enabled
tool's full signature at startup."""
LOG_FORMAT: Final = "%(asctime)s %(levelname)s %(name)s %(message)s"


class QuietExpectedErrors(logging.Filter):
    """Drop tracebacks from records below ERROR."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """Strip the traceback from expected-error records.

        Args:
            record (logging.LogRecord): Record being logged.

        Returns:
            bool: Always True; the record itself is kept.
        """
        if record.levelno < logging.ERROR and record.exc_info:
            record.exc_info = None
            record.exc_text = None
        return True


def _add_once(logger: logging.Logger, kind: type[logging.Filter]) -> None:
    """Attach a filter type to a logger unless it is already attached.

    Args:
        logger (logging.Logger): Logger to protect.
        kind (type[logging.Filter]): Filter class.
    """
    if not any(isinstance(item, kind) for item in logger.filters):
        logger.addFilter(kind())


def quiet_expected_errors() -> None:
    """Install the traceback filter on FastMCP's server logger once per process."""
    _add_once(logging.getLogger(FASTMCP_SERVER_LOGGER), QuietExpectedErrors)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure process logging for the server: redacted output, quiet HTTP clients and worker.

    Args:
        level (int): Root log level.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RedactingFormatter(LOG_FORMAT))
        if not any(isinstance(item, RedactSecrets) for item in handler.filters):
            handler.addFilter(RedactSecrets())
    for name in (*HTTP_LOGGERS, *QUIET_LOGGERS):
        logging.getLogger(name).setLevel(logging.WARNING)
    protect_secrets()
    quiet_expected_errors()
