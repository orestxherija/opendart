"""Keep the OpenDART API key out of logs.

FSS requires the API key as the ``crtfc_key`` query parameter, so every request URL carries
it, and httpx2 logs each request URL at INFO. Creating an ``OpenDart`` client attaches
``RedactSecrets`` to the HTTP client loggers, which rewrites records before any handler
sees them. Applications that render records elsewhere can use ``RedactingFormatter`` or
``redact`` too.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from collections.abc import Iterable

# Logger filters apply only to records created on that logger, not to records propagated
# from children, so every emitting logger is listed. httpcore2 creates some lazily.
HTTP_LOGGERS: Final = (
    "httpx2",
    "httpcore2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "httpcore2.proxy",
    "httpcore2.socks",
)
REDACTED: Final = "[REDACTED]"

_SECRET = re.compile(r"(crtfc_key=)[^&\s\"'<>]+", re.IGNORECASE)


def redact(text: str, *secrets: str) -> str:
    """Replace API key values in text.

    Args:
        text (str): Log text, URL, exception message, or traceback.
        *secrets (str): Known secret values to replace wherever they appear.

    Returns:
        str: Text with every ``crtfc_key`` value and every known secret replaced.
    """
    text = _SECRET.sub(rf"\g<1>{REDACTED}", text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class RedactSecrets(logging.Filter):
    """Rewrite records whose message carries the API key."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the formatted message in place.

        Args:
            record (logging.LogRecord): Record being logged.

        Returns:
            bool: Always True; the record itself is kept.
        """
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts the API key from the whole rendered record."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Render a record, including any traceback, without the API key.

        Args:
            record (logging.LogRecord): Record being formatted.

        Returns:
            str: Redacted text.
        """
        return redact(super().format(record))


def _descendants(names: tuple[str, ...]) -> list[str]:
    """List existing loggers below the named ones.

    Args:
        names (tuple[str, ...]): Parent logger names.

    Returns:
        list[str]: Names of already created child loggers.
    """
    prefixes = tuple(f"{name}." for name in names)
    existing = list(logging.root.manager.loggerDict.items())
    return [
        name
        for name, item in existing
        if isinstance(item, logging.Logger) and name.startswith(prefixes)
    ]


def protect_loggers(names: Iterable[str] = HTTP_LOGGERS) -> None:
    """Attach ``RedactSecrets`` once to each named logger and its existing children.

    Idempotent; levels, handlers, and other filters are left as they are.

    Args:
        names (Iterable[str]): Logger names. Defaults to the httpx2 and httpcore2 loggers.
    """
    parents = tuple(names)
    for name in dict.fromkeys(parents + tuple(_descendants(parents))):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactSecrets) for item in logger.filters):
            logger.addFilter(RedactSecrets())
