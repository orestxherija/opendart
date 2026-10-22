"""Session factories with application-owned transaction boundaries.

A factory can be shared; each concurrent task/thread needs its own session.
Use ``with factory.begin() as session:`` or its async equivalent to commit on
success, roll back on failure, and close the session. Query functions receive
that session and never commit it. ``with factory() as session:`` closes and
rolls back uncommitted work, including a transaction opened by a SELECT.

expire_on_commit=False lets already-loaded scalar attributes remain usable
without surprise refresh I/O after commit, especially in async code. Those
values may become stale; refresh explicitly when freshness is required. This
does not make unloaded relationships safe to access after session closure.
"""

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create independent sync sessions over an application-owned engine."""
    return sessionmaker(engine, expire_on_commit=False)


def async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create independent async sessions; never share one across tasks."""
    return async_sessionmaker(engine, expire_on_commit=False)
