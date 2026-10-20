"""Immutable, explicitly loaded SDK configuration."""

from functools import lru_cache
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def _english_api_url(value: HttpUrl) -> HttpUrl:
    """Validate an HTTPS API URL without embedded credentials or query data.

    Args:
        value (HttpUrl): Parsed candidate upstream URL.

    Returns:
        HttpUrl: The accepted URL, unchanged.

    Raises:
        ValueError: The URL is not HTTPS, contains credentials, a query or fragment, or
            targets the Korean OpenDART host.
    """
    if value.scheme != "https" or value.username or value.password or value.query or value.fragment:
        raise ValueError("base_url must be HTTPS without credentials, query, or fragment")
    if value.host == "opendart.fss.or.kr":
        raise ValueError("the Korean OpenDART service is not supported by this English SDK")
    return value


ApiKey = Annotated[SecretStr, Field(min_length=40, max_length=40)]
Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
PoolSize = Annotated[int, Field(ge=1, strict=True)]
IdlePoolSize = Annotated[int, Field(ge=0, strict=True)]
ByteLimit = Annotated[int, Field(ge=1, strict=True)]
ApiUrl = Annotated[HttpUrl, AfterValidator(_english_api_url)]


class SettingsGroup(BaseModel):
    """Base for immutable settings groups that reject unknown fields.

    Nested groups validate explicit input; only the root Settings model reads environment
    variables.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class OpenDartSettings(SettingsGroup):
    """Configure one English OpenDART upstream and its owned HTTP pool.

    Timeouts apply to individual HTTP phases; they do not impose a total request deadline.
    Settings are immutable.

    Args:
        api_key (SecretStr): Required 40-character FSS API key.
        base_url (HttpUrl): HTTPS upstream URL without credentials, query, or fragment.
            Defaults to https://engopendart.fss.or.kr/engapi/.
        connect_timeout (float): Positive finite connection timeout in seconds. Defaults to
            5.0.
        timeout (float): Positive finite read, write, and pool timeout in seconds. Defaults
            to 5.0.
        max_connections (int): Positive total connection limit. Defaults to 100.
        max_keepalive_connections (int): Nonnegative idle connection limit, at most
            max_connections. Defaults to 20.
        max_response_bytes (int): Positive maximum JSON response size in bytes. Defaults to
            32 MiB.
        max_download_bytes (int): Positive maximum ZIP response size in bytes. Defaults to
            128 MiB.

    Raises:
        pydantic.ValidationError: A value violates its type or constraint, or the idle pool
            limit exceeds the total pool limit.
    """

    api_key: ApiKey
    base_url: ApiUrl = HttpUrl("https://engopendart.fss.or.kr/engapi/")
    connect_timeout: Seconds = 5.0
    timeout: Seconds = 5.0
    max_connections: PoolSize = 100
    max_keepalive_connections: IdlePoolSize = 20
    max_response_bytes: ByteLimit = 32 * 1024 * 1024
    max_download_bytes: ByteLimit = 128 * 1024 * 1024

    @model_validator(mode="after")
    def _pool_bounds(self) -> Self:
        """Validate that the idle pool fits within the total connection limit.

        Returns:
            Self: The validated settings instance.

        Raises:
            ValueError: max_keepalive_connections exceeds max_connections.
        """
        if self.max_keepalive_connections > self.max_connections:
            raise ValueError("max_keepalive_connections must not exceed max_connections")
        return self


class Settings(BaseSettings):
    """Load immutable SDK settings from explicit input and OPENDART_API__* variables.

    Environment variables override dotenv values. Unrelated root keys are ignored; unknown
    nested API fields are rejected. Other BaseSettings keyword options are inherited.

    Args:
        api (OpenDartSettings): Upstream settings. May instead be supplied through nested
            OPENDART_API__* environment variables.
        _env_file (str | Path | Sequence[str | Path] | None): Optional dotenv file or files
            passed to BaseSettings. No dotenv file is loaded unless explicitly supplied.

    Raises:
        pydantic.ValidationError: Required configuration is missing or invalid.
        pydantic_settings.SettingsError: An environment or dotenv value cannot be parsed by
            a settings source.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENDART_",
        env_nested_delimiter="__",
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
    )
    api: OpenDartSettings


@lru_cache
def get_settings() -> Settings:
    """Load and cache the process-wide settings on first use.

    Call get_settings.cache_clear() to reload after changing the environment. This factory
    does not load dotenv files.

    Returns:
        Settings: The cached, immutable SDK configuration.

    Raises:
        pydantic.ValidationError: Required configuration is missing or invalid.
        pydantic_settings.SettingsError: An environment value cannot be parsed by a settings
            source.
    """
    return Settings()
