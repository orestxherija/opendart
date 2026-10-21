"""Classify structured database errors without exposing SQL, values, or messages.

Suggested module: app.db_errors. Backend must match the actual connection.
A retryable classification only permits restarting a rolled-back transaction;
it never establishes that a callback's external side effects can be repeated.
"""

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import DBAPIError, TimeoutError

Backend = Literal["sqlite", "postgresql"]
FailureKind = Literal[
    "constraint",
    "contention",
    "connection",
    "timeout",
    "cancelled",
    "programming",
    "unknown",
]


@dataclass(frozen=True)
class Failure:
    """Safe metadata; contains no exception message or connection credentials."""

    kind: FailureKind
    code: str | None = None
    retry_transaction: bool = False


def classify_error(error: Exception, *, backend: Backend) -> Failure:
    """Recognize SQLSTATE / SQLite result codes; never classify by message text."""
    if isinstance(error, TimeoutError):
        return Failure("timeout")
    if isinstance(error, DBAPIError) and error.connection_invalidated:
        # A lost connection, especially during COMMIT, has an uncertain outcome.
        return Failure("connection")
    original = error.orig if isinstance(error, DBAPIError) else error
    if backend == "postgresql":
        code = getattr(original, "sqlstate", None)
        if not isinstance(code, str) or re.fullmatch(r"[0-9A-Z]{5}", code) is None:
            return Failure("unknown")
        if code in {"40001", "40P01"}:
            return Failure("contention", code, retry_transaction=True)
        if code.startswith("23"):
            return Failure("constraint", code)
        if code.startswith("08"):
            return Failure("connection", code)
        if code == "57014":
            return Failure("cancelled", code)
        if code.startswith("42"):
            return Failure("programming", code)
        return Failure("unknown", code)
    if backend == "sqlite":
        code = getattr(original, "sqlite_errorcode", None)
        if not isinstance(code, int):
            return Failure("unknown")
        primary = code & 0xFF
        if primary == sqlite3.SQLITE_BUSY:
            return Failure("contention", str(code), retry_transaction=True)
        if primary == sqlite3.SQLITE_LOCKED:
            # Usually requires fixing connection/cursor ownership, not waiting.
            return Failure("contention", str(code))
        if primary == sqlite3.SQLITE_CONSTRAINT:
            return Failure("constraint", str(code))
        if primary == sqlite3.SQLITE_INTERRUPT:
            return Failure("cancelled", str(code))
        return Failure("unknown", str(code))
    raise ValueError("unsupported database backend")
