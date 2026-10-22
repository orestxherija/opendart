"""Small typed query adapters; callers own sessions and transactions.

Projection reads return detached immutable values with no lazy database I/O.
Updates use an ORM object and leave flushing/commit to the caller, allowing
several operations to form one transaction. The object lookup can add a SELECT;
choose an explicit UPDATE for high-volume workloads where that matters.
SQLAlchemy binds the supplied values; never interpolate them into SQL text.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db_models import Customer


@dataclass(frozen=True)
class CustomerRecord:
    """A database-independent result that survives session closure."""

    id: int
    email: str


def get_customer(session: Session, customer_id: int) -> CustomerRecord | None:
    """Project one existing customer without exposing a session-bound object."""
    row = session.execute(
        select(Customer.id, Customer.email).where(Customer.id == customer_id)
    ).one_or_none()
    if row is None:
        return None
    return CustomerRecord(id=row[0], email=row[1])


async def get_customer_async(
    session: AsyncSession, customer_id: int
) -> CustomerRecord | None:
    """Async projection read; closing the session also ends its read transaction."""
    row = (
        await session.execute(
            select(Customer.id, Customer.email).where(Customer.id == customer_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return CustomerRecord(id=row[0], email=row[1])


def update_email(session: Session, customer_id: int, email: str) -> bool:
    """Stage an ORM change; return False if absent, without flushing or commit."""
    customer = session.get(Customer, customer_id)
    if customer is None:
        return False
    customer.email = email
    return True


async def update_email_async(
    session: AsyncSession, customer_id: int, email: str
) -> bool:
    """Stage an async ORM change; the owning transaction decides its outcome."""
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return False
    customer.email = email
    return True
