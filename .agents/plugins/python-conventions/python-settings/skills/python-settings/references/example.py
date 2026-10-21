"""Application settings.

Single source of truth for configuration. Consumers call ``get_settings()``;
nothing instantiates ``Settings`` directly outside of tests.

Values are resolved in this order, highest priority first: init arguments,
environment variables, ``.env`` file, secrets directory, ``config.toml``,
field defaults.

Example:
    Non-secret defaults in ``config.toml``::

        env = "prod"

        [database]
        host = "db.internal"
        user = "app"
        name = "app"
        pool_max = 20

        [tls]
        enabled = true
        cert_path = "/etc/ssl/app.crt"
        key_path = "/etc/ssl/app.key"

    Secrets and overrides from the environment::

        APP_DATABASE__PASSWORD=s3cret
        APP_AUTH__ISSUER=https://idp.example.com

    Access from application code::

        from app.settings import get_settings

        settings = get_settings()
        dsn = settings.database.dsn.get_secret_value()
"""

from functools import cached_property, lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import quote

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    FilePath,
    SecretStr,
    StringConstraints,
    computed_field,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

Port = Annotated[int, Field(ge=1, le=65535)]
"""A valid TCP port number (1-65535)."""

PoolSize = Annotated[int, Field(ge=1, le=500)]
"""A connection pool size (1-500)."""

Hostname = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1)
]
"""A non-empty hostname, stripped of whitespace and lowercased."""

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""A non-empty identifier, stripped of whitespace."""


class SettingsGroup(BaseModel):
    """Base class for nested settings groups.

    Groups are immutable and reject unknown keys so configuration typos
    fail loudly at startup. All nested groups inherit from this class.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class DatabaseSettings(SettingsGroup):
    """Database connection and pooling configuration.

    Attributes:
        host (str): Database hostname.
        port (int): Database TCP port.
        user (str): Database user name.
        password (SecretStr): Database password.
        name (str): Database name.
        pool_min (int): Minimum number of pooled connections.
        pool_max (int): Maximum number of pooled connections.
        dsn (SecretStr): PostgreSQL connection URL including credentials.
    """

    host: Hostname = Field(default="localhost", description="Database hostname.")
    port: Port = Field(default=5432, description="Database TCP port.")
    user: Identifier = Field(description="Database user name.")
    password: SecretStr = Field(description="Database password.")
    name: Identifier = Field(description="Database name.")
    pool_min: PoolSize = Field(
        default=1, description="Minimum number of pooled connections."
    )
    pool_max: PoolSize = Field(
        default=10, description="Maximum number of pooled connections."
    )

    @model_validator(mode="after")
    def _check_pool_bounds(self) -> Self:
        """Ensure the pool minimum does not exceed the maximum.

        Cross-field rule within a single group, so it lives here and not
        on the root settings.

        Returns:
            Self: The validated instance.

        Raises:
            ValueError: If ``pool_min`` is greater than ``pool_max``.
        """
        if self.pool_min > self.pool_max:
            raise ValueError(
                f"pool_min ({self.pool_min}) must be <= pool_max ({self.pool_max})"
            )
        return self

    @computed_field(description="PostgreSQL connection URL including credentials.")
    @cached_property
    def dsn(self) -> SecretStr:
        """Build the PostgreSQL connection URL from the connection fields.

        Purely derived from other fields, so it is a computed field rather
        than a validator. Computed once per instance and cached. Returned as
        ``SecretStr`` because it embeds the password and computed fields
        appear in ``model_dump()``.

        Returns:
            SecretStr: The URL-encoded connection string.
        """
        user = quote(self.user, safe="")
        password = quote(self.password.get_secret_value(), safe="")
        return SecretStr(
            f"postgresql://{user}:{password}@{self.host}:{self.port}/{self.name}"
        )


class TlsSettings(SettingsGroup):
    """TLS termination configuration.

    Attributes:
        enabled (bool): Whether TLS is enabled.
        cert_path (Path | None): Path to the PEM certificate.
        key_path (Path | None): Path to the PEM private key.
    """

    enabled: bool = Field(default=False, description="Whether TLS is enabled.")
    cert_path: FilePath | None = Field(
        default=None, description="Path to the PEM certificate."
    )
    key_path: FilePath | None = Field(
        default=None, description="Path to the PEM private key."
    )

    @model_validator(mode="after")
    def _check_material_present(self) -> Self:
        """Require certificate and key paths when TLS is enabled.

        Returns:
            Self: The validated instance.

        Raises:
            ValueError: If ``enabled`` is true and either ``cert_path`` or
                ``key_path`` is missing.
        """
        if self.enabled and not (self.cert_path and self.key_path):
            raise ValueError("tls.enabled requires both cert_path and key_path")
        return self


class AuthSettings(SettingsGroup):
    """Token authentication configuration.

    Attributes:
        issuer (AnyHttpUrl | None): Token issuer URL. Required when
            ``require_auth`` is true (enforced on the root settings).
        require_auth (bool): Whether to reject unauthenticated requests.
    """

    issuer: AnyHttpUrl | None = Field(
        default=None,
        description="Token issuer URL. Required when require_auth is true.",
    )
    require_auth: bool = Field(
        default=False, description="Whether to reject unauthenticated requests."
    )


class Settings(BaseSettings):
    """Root application settings, loaded from the environment and ``config.toml``.

    Attributes:
        env (Literal["dev", "staging", "prod"]): Deployment environment.
        database (DatabaseSettings): Database connection and pooling.
        tls (TlsSettings): TLS termination.
        auth (AuthSettings): Token authentication.
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        env_file=".env",
        toml_file="config.toml",
        frozen=True,
        extra="ignore",
    )

    env: Literal["dev", "staging", "prod"] = Field(
        default="dev", description="Deployment environment."
    )
    database: DatabaseSettings = Field(description="Database connection and pooling.")
    tls: TlsSettings = Field(
        default_factory=TlsSettings, description="TLS termination."
    )
    auth: AuthSettings = Field(
        default_factory=AuthSettings, description="Token authentication."
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Add ``config.toml`` as the lowest-priority source.

        This is the only supported way to load non-environment values.
        Sources are listed from highest to lowest priority, so environment
        variables and secrets always override the TOML file.

        Args:
            settings_cls (type[BaseSettings]): The settings class being built.
            init_settings (PydanticBaseSettingsSource): Init keyword arguments.
            env_settings (PydanticBaseSettingsSource): Environment variables.
            dotenv_settings (PydanticBaseSettingsSource): The ``.env`` file.
            file_secret_settings (PydanticBaseSettingsSource): Secrets directory.

        Returns:
            tuple[PydanticBaseSettingsSource, ...]: Sources in priority order.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            TomlConfigSettingsSource(settings_cls),
        )

    @model_validator(mode="after")
    def _check_cross_group_rules(self) -> Self:
        """Validate invariants that span multiple groups.

        These live on the root because no single child group owns all of
        the fields involved.

        Returns:
            Self: The validated instance.

        Raises:
            ValueError: If ``auth.require_auth`` is true without
                ``auth.issuer``, or if ``env`` is ``"prod"`` without
                ``tls.enabled``.
        """
        if self.auth.require_auth and self.auth.issuer is None:
            raise ValueError("auth.require_auth requires auth.issuer to be set")
        if self.env == "prod" and not self.tls.enabled:
            raise ValueError("tls.enabled must be true when env is 'prod'")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    The result is cached so all sources are read and validated once.
    In tests, call ``get_settings.cache_clear()`` after changing the
    environment.

    Returns:
        Settings: The validated, immutable application settings.

    Raises:
        pydantic.ValidationError: If the merged sources fail validation.
    """
    return Settings()
