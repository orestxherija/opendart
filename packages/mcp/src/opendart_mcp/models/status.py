"""The server status document: directory, upstream usage, caches, metrics, and settings.

It never contains the API key, and the cache directory is the only file path it shows.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from opendart_analysis.documents.models import DocumentStoreStats
from opendart_mcp.models.common import OutputModel


class DirectoryStatus(OutputModel):
    """Company directory state."""

    status: Literal["loading", "ready", "failed", "disabled"]
    companies: int
    listed: int
    loaded_at: datetime | None = Field(default=None, description="When the archive was downloaded.")
    source: str | None = Field(default=None, description="disk or download.")
    error: str | None = Field(default=None, description="Last load failure.")


class UpstreamUsage(OutputModel):
    """OpenDART requests, counted like the daily quota."""

    day: date | None = Field(default=None, description="KST day of the daily counter.")
    today: int = Field(description="Requests that day, including retries.")
    total: int = Field(description="Requests since the server started.")
    failures: int = Field(description="Requests that failed after one retry.")
    in_flight: int = Field(description="Distinct requests running now.")
    by_operation: dict[str, int] = Field(description="Requests per SDK method since start.")


class CacheStatus(OutputModel):
    """Response cache behind the gateway."""

    entries: int
    weight: int = Field(description="Cached upstream records.")
    max_weight: int
    hits: int
    misses: int


class ComponentUsage(OutputModel):
    """Calls to one tool, resource, or prompt since the server started."""

    calls: int
    errors: int
    error_types: dict[str, int] = Field(default_factory=dict)
    avg_ms: float
    max_ms: float
    upstream: int = Field(description="OpenDART requests the calls caused.")


class StatusSettings(OutputModel):
    """Configuration that explains the server's behavior; no secrets."""

    cache_ttl_seconds: dict[str, float] = Field(description="Response cache lifetime by data.")
    client_cache_ttl_seconds: int | None = Field(
        default=None, description="Cache hint sent to clients."
    )
    upstream_concurrency: int
    upstream_timeout_seconds: float
    response_cache_records: int
    task_concurrency: int
    service_tools_enabled: bool
    elicit_ambiguous_company: bool
    directory_cache_dir: str | None = None
    directory_max_age_hours: float
    document_cache_chars: int


class ServerStatus(OutputModel):
    """Health and usage of the server."""

    as_of: datetime = Field(description="Current time in KST.")
    version: str
    started: datetime
    uptime_seconds: int
    api_key_configured: bool
    directory: DirectoryStatus
    upstream: UpstreamUsage | None = Field(default=None, description="Absent without an API key.")
    response_cache: CacheStatus
    documents: DocumentStoreStats | None = Field(
        default=None, description="Filing document cache; absent without an API key."
    )
    components: dict[str, ComponentUsage] = Field(description="Usage per component.")
    settings: StatusSettings
