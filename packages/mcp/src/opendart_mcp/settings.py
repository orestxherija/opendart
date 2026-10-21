"""Immutable configuration for the local MCP HTTP listener."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Port = Annotated[int, Field(ge=1, le=65535)]


class SettingsGroup(BaseModel):
    """Base for immutable settings groups that reject unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HttpSettings(SettingsGroup):
    """Configure the listener; wildcard binding is used inside Docker only."""

    host: Literal["127.0.0.1", "localhost", "0.0.0.0"] = "127.0.0.1"
    port: Port = 8000


class Settings(BaseSettings):
    """Load OPENDART_MCP_HTTP__* variables without requiring an API key.

    Dotenv files are loaded only when explicitly supplied through _env_file.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENDART_MCP_",
        env_nested_delimiter="__",
        frozen=True,
        extra="ignore",
    )
    http: HttpSettings = Field(default_factory=HttpSettings)


@lru_cache
def get_settings() -> Settings:
    """Load and cache the process-wide MCP configuration on first use.

    Returns:
        Settings: Validated, immutable listener configuration.
    """
    return Settings()
