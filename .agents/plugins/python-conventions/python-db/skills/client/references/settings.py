"""Frozen settings groups for SQLite and PostgreSQL clients.

Nest these groups in an application-owned root settings object. Environment,
TOML, and secret-source loading belong to that root, following python-settings.
Do not log DSNs, rendered engine URLs, or ValidationError.errors()/json(): raw
validation payloads may retain input even when error text hides it.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


class DatabaseSettingsGroup(BaseModel):
    """Configuration values only; no environment reads or resources."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        hide_input_in_errors=True,
    )


class SQLiteSettings(DatabaseSettingsGroup):
    """An ordinary file path, or ``:memory:`` for serial disposable work.

    ``timeout_seconds`` bounds lock waits and acquisition of the one pooled
    file connection separately; it is not an end-to-end query deadline.
    SQLite URI filenames and SQLAlchemy URLs are deliberately not accepted.
    """

    database: str
    timeout_seconds: Seconds = 5.0

    @field_validator("database")
    @classmethod
    def _check_database(cls, value: str) -> str:
        if (
            not value.strip()
            or "\x00" in value
            or value.startswith(("file:", "sqlite:"))
            or value.startswith("sqlite+")
        ):
            raise ValueError("use a SQLite file path or :memory:")
        return value


def _postgresql_url(dsn: SecretStr) -> URL:
    """Validate without echoing the supplied URL, including malformed ports."""
    try:
        url = make_url(dsn.get_secret_value())
    except (ArgumentError, ValueError):
        raise ValueError("invalid PostgreSQL connection URL") from None
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("use a postgresql or postgresql+psycopg URL")
    if not url.database:
        raise ValueError("PostgreSQL URL must name a database")
    sslmode = url.query.get("sslmode", "verify-full")
    if not isinstance(sslmode, str) or sslmode not in {
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise ValueError("invalid PostgreSQL sslmode")
    return url.set(drivername="postgresql+psycopg").update_query_dict(
        {"sslmode": sslmode}
    )


class PostgreSQLSettings(DatabaseSettingsGroup):
    """One PostgreSQL endpoint with a bounded SQLAlchemy-owned pool.

    TLS defaults to ``verify-full``; supply the cloud provider's CA through
    ``sslrootcert`` in the DSN when required. Explicit DSN sslmode overrides
    that default, including ``disable`` for isolated local tests. Psycopg's
    connect timeout is per host, not a whole-operation deadline.
    """

    dsn: SecretStr
    pool_size: PositiveInt = 5
    max_overflow: NonNegativeInt = 0
    pool_timeout_seconds: Seconds = 10.0
    connect_timeout_seconds: PositiveInt = 10

    @field_validator("dsn")
    @classmethod
    def _check_dsn(cls, value: SecretStr) -> SecretStr:
        _postgresql_url(value)
        return value

    def sqlalchemy_url(self) -> URL:
        """Return connection configuration containing secrets; never log it."""
        return _postgresql_url(self.dsn)


DatabaseSettings = SQLiteSettings | PostgreSQLSettings
