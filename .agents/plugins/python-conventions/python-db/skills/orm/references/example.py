"""A typed mapping describing an existing customers table.

Adapt names, nullability, constraints and types to the actual database schema.
Defining these classes issues no SQL and creates no tables. Application startup
must not call create_all(); disposable test fixtures may create their own schema.
Integer primary keys work with SQLite's INTEGER PRIMARY KEY behavior and with
PostgreSQL. A String length is not enforced by SQLite as it is by PostgreSQL;
validate application input separately if that guarantee is required.
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Application-owned registry of mappings; not a schema management tool."""


class Customer(Base):
    """An existing customer row, managed by the session that loaded it."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
