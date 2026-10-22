"""Opt-in whole-transaction retries with a fresh session for every attempt.

Suggested module: app.db_retries. The callback may flush, but must not commit,
roll back, close the session, or retain live results/ORM instances for later use.
Return detached values. replay_safe=True asserts that ALL callback work can be
repeated (including non-database effects). Connection failures never auto-replay.
The elapsed budget bounds retries and backoff, not an already-running statement
or commit. Configure driver/server timeouts and, for async work, a caller deadline.
"""

from asyncio import sleep as async_sleep
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from math import isfinite
from random import uniform
from time import monotonic, sleep
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.db_errors import Backend, classify_error

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.05
    max_backoff_seconds: float = 1.0
    max_elapsed_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        values = (
            self.initial_backoff_seconds,
            self.max_backoff_seconds,
            self.max_elapsed_seconds,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("retry durations must be finite")
        if not 0 <= self.initial_backoff_seconds <= self.max_backoff_seconds:
            raise ValueError("backoff must be nonnegative and ordered")
        if self.max_elapsed_seconds <= 0:
            raise ValueError("max_elapsed_seconds must be positive")


_DEFAULT_POLICY = RetryPolicy()


def _delay(policy: RetryPolicy, attempt: int) -> float:
    return uniform(
        0,
        min(
            policy.max_backoff_seconds,
            policy.initial_backoff_seconds * 2 ** (attempt - 1),
        ),
    )


def run_transaction(
    factory: sessionmaker[Session],
    operation: Callable[[Session], T],
    *,
    backend: Backend,
    replay_safe: bool = False,
    policy: RetryPolicy = _DEFAULT_POLICY,
) -> T:
    """Commit one unit of work; opt into bounded replay of known contention."""
    deadline = monotonic() + policy.max_elapsed_seconds
    attempt = 1
    while True:
        try:
            with factory.begin() as session:
                value = operation(session)
            return value
        except Exception as error:
            # The context has rolled back and closed before classification/sleep.
            if (
                not replay_safe
                or attempt >= policy.max_attempts
                or not classify_error(error, backend=backend).retry_transaction
            ):
                raise
            delay = _delay(policy, attempt)
            if delay >= deadline - monotonic():
                raise
            sleep(delay)
            if monotonic() >= deadline:
                raise
            attempt += 1


async def run_transaction_async(
    factory: async_sessionmaker[AsyncSession],
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    backend: Backend,
    replay_safe: bool = False,
    policy: RetryPolicy = _DEFAULT_POLICY,
) -> T:
    """Async equivalent; cancellation propagates through transaction cleanup."""
    deadline = monotonic() + policy.max_elapsed_seconds
    attempt = 1
    while True:
        try:
            async with factory.begin() as session:
                value = await operation(session)
            return value
        except Exception as error:
            if (
                not replay_safe
                or attempt >= policy.max_attempts
                or not classify_error(error, backend=backend).retry_transaction
            ):
                raise
            delay = _delay(policy, attempt)
            if delay >= deadline - monotonic():
                raise
            await async_sleep(delay)
            if monotonic() >= deadline:
                raise
            attempt += 1
