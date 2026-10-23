"""Immutable server configuration, loaded from OPENDART_MCP_* environment variables.

The OpenDART API key is read separately by the SDK (OPENDART_API__API_KEY or the
/run/secrets file), so the server starts without one and reports the missing key when a
tool needs it.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Port = Annotated[int, Field(ge=1, le=65535)]
Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]


def default_cache_dir() -> Path:
    """Choose the per-user cache directory for downloaded reference data.

    Returns:
        Path: ``$XDG_CACHE_HOME/opendart-mcp``, defaulting to ``~/.cache/opendart-mcp``.
    """
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(base).expanduser() / "opendart-mcp"


class SettingsGroup(BaseModel):
    """Base for immutable settings groups that reject unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HttpSettings(SettingsGroup):
    """Configure the listener and protocol-level behavior.

    Wildcard binding is used inside Docker only.

    Attributes:
        host (str): Bind address.
        port (int): Listener port.
        cache_ttl (int | None): Seconds clients may cache lists and resource reads (sent as
            ``ttlMs`` with private scope to 2026-07-28 clients); None sends no hint.
        list_page_size (int | None): Page size for tools/resources/prompts lists; None
            returns every component in one page.
        rate_limit (float | None): Requests per second across all clients; None disables
            rate limiting.
        rate_burst (int): Requests allowed in a burst above the rate.
    """

    host: Literal["127.0.0.1", "localhost", "0.0.0.0"] = "127.0.0.1"
    port: Port = 8000
    cache_ttl: Annotated[int, Field(ge=1, le=86_400)] | None = 300
    list_page_size: Annotated[int, Field(ge=1, le=1000)] | None = None
    rate_limit: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = 20.0
    rate_burst: Annotated[int, Field(ge=1)] = 50


class TaskSettings(SettingsGroup):
    """In-process background tasks for task-capable clients.

    Attributes:
        concurrency (int): Background tasks running at once; more are queued.
        queue (str): Task queue name, unique per server in one process.
    """

    concurrency: Annotated[int, Field(ge=1, le=32)] = 4
    queue: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")] = (
        "opendart"
    )


class ToolSettings(SettingsGroup):
    """Optional components and interaction behavior.

    Attributes:
        enable_service_tools (bool): Register the list_services and call_service escape
            hatches for direct access to any upstream service. Off by default.
        elicit_ambiguous_company (bool): Ask hosts that support elicitation to choose among
            matching companies instead of failing with a candidate list.
    """

    enable_service_tools: bool = False
    elicit_ambiguous_company: bool = True


class UpstreamSettings(SettingsGroup):
    """Access to OpenDART JSON services.

    Attributes:
        timeout (float): Read, write, and pool timeout in seconds. OpenDART can pause for
            several seconds mid-response, so this exceeds the SDK's default.
        connect_timeout (float): Connection timeout in seconds.
        max_concurrency (int): Simultaneous upstream requests across all tool calls.
        retry_delay (float): Seconds before the single retry of a transient failure.
        cache_records (int): Response cache bound, in upstream records.
    """

    timeout: Seconds = 30.0
    connect_timeout: Seconds = 10.0
    max_concurrency: Annotated[int, Field(ge=1, le=20)] = 5
    retry_delay: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    cache_records: Annotated[int, Field(ge=100)] = 50_000


class DirectorySettings(SettingsGroup):
    """Download, on-disk cache, and refresh of the company directory.

    The directory archive is about 3.6 MB but OpenDART can take minutes to send it, so the
    server loads it in the background and keeps a copy on disk between restarts.

    Attributes:
        cache_dir (Path | None): Directory for the cached archive; None disables disk caching.
        max_age_hours (float): Age after which the archive is downloaded again.
        deadline (float): Overall download deadline in seconds. The download shares the
            document client and its per-phase timeouts (``documents.timeout``).
        wait (float): Seconds a tool waits for a loading directory before answering that it
            is still loading.
    """

    cache_dir: Path | None = Field(default_factory=default_cache_dir)
    max_age_hours: Annotated[float, Field(gt=0, le=24 * 7)] = 24.0
    deadline: Seconds = 900.0
    wait: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 15.0


class DocumentSettings(SettingsGroup):
    """Download and caching of original filing documents.

    Attributes:
        timeout (float): Per-phase download timeout in seconds.
        connect_timeout (float): Connection timeout in seconds.
        wait (float): Seconds a tool call waits for a download before answering that it is
            still in progress; the download continues and its result is cached.
        cache_chars (int): Bound on cached rendered text, in characters. A cached filing
            holds about 12 bytes per rendered character, so the default keeps the cache near
            50 MB; a large annual report renders to about 0.7 million characters.
    """

    timeout: Seconds = 90.0
    connect_timeout: Seconds = 10.0
    wait: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 45.0
    cache_chars: Annotated[int, Field(ge=100_000)] = 4_000_000


class Settings(BaseSettings):
    """Load OPENDART_MCP_* variables without requiring an API key.

    Nested groups use a double underscore, for example OPENDART_MCP_HTTP__PORT. Dotenv
    files are loaded only when explicitly supplied through _env_file.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENDART_MCP_",
        env_nested_delimiter="__",
        frozen=True,
        extra="ignore",
    )
    http: HttpSettings = Field(default_factory=HttpSettings)
    tasks: TaskSettings = Field(default_factory=TaskSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    upstream: UpstreamSettings = Field(default_factory=UpstreamSettings)
    directory: DirectorySettings = Field(default_factory=DirectorySettings)
    documents: DocumentSettings = Field(default_factory=DocumentSettings)


@lru_cache
def get_settings() -> Settings:
    """Load and cache the process-wide MCP configuration on first use.

    Returns:
        Settings: Validated, immutable server configuration.
    """
    return Settings()
