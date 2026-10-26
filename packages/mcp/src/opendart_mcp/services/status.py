"""Server status: directory state, upstream usage, cache statistics, metrics, and settings."""

from __future__ import annotations

from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.dates import KST
from opendart_mcp.core.ttl import DAY, FILINGS, HOUR
from opendart_mcp.models.status import (
    CacheStatus,
    ComponentUsage,
    DirectoryStatus,
    ServerStatus,
    StatusSettings,
    UpstreamUsage,
)

if TYPE_CHECKING:
    from datetime import datetime

    from opendart_mcp.core.gateway import Gateway
    from opendart_mcp.core.metrics import ComponentStats
    from opendart_mcp.core.state import AppState
    from opendart_mcp.settings import Settings

VERSION: Final = version("opendart-mcp")
_TTLS: Final = {"profiles_reports_statements": DAY, "events": HOUR, "filing_searches": FILINGS}


def _kst(moment: datetime | None) -> datetime | None:
    """Express an aware time in KST.

    Args:
        moment (datetime | None): Aware time.

    Returns:
        datetime | None: The same instant in KST, to the second.
    """
    return moment.astimezone(KST).replace(microsecond=0) if moment else None


def _upstream(gateway: Gateway | None) -> UpstreamUsage | None:
    """Summarize upstream usage.

    Args:
        gateway (Gateway | None): Upstream access; None without an API key.

    Returns:
        UpstreamUsage | None: Counters, or None without an API key.
    """
    if gateway is None:
        return None
    usage = gateway.usage
    return UpstreamUsage(
        day=date.fromisoformat(usage.day) if usage.day else None,
        today=usage.today,
        total=usage.total,
        failures=usage.failures,
        in_flight=gateway.in_flight,
        by_operation=dict(sorted(usage.by_operation.items())),
    )


def _component(stats: ComponentStats) -> ComponentUsage:
    """Summarize one component's counters.

    Args:
        stats (ComponentStats): Raw counters.

    Returns:
        ComponentUsage: Calls, errors, latency, and upstream requests.
    """
    return ComponentUsage(
        calls=stats.calls,
        errors=sum(stats.errors.values()),
        error_types=dict(stats.errors),
        avg_ms=round(stats.total_ms / stats.calls, 1) if stats.calls else 0.0,
        max_ms=round(stats.max_ms, 1),
        upstream=stats.upstream,
    )


def _settings(settings: Settings) -> StatusSettings:
    """Select the settings that explain behavior, without secrets.

    Args:
        settings (Settings): Server configuration.

    Returns:
        StatusSettings: Non-secret settings.
    """
    return StatusSettings(
        cache_ttl_seconds=_TTLS,
        client_cache_ttl_seconds=settings.http.cache_ttl,
        upstream_concurrency=settings.upstream.max_concurrency,
        upstream_timeout_seconds=settings.upstream.timeout,
        response_cache_records=settings.upstream.cache_records,
        task_concurrency=settings.tasks.concurrency,
        service_tools_enabled=settings.tools.enable_service_tools,
        elicit_ambiguous_company=settings.tools.elicit_ambiguous_company,
        directory_cache_dir=_home_relative(settings.directory.cache_dir),
        directory_max_age_hours=settings.directory.max_age_hours,
        document_cache_chars=settings.documents.cache_chars,
    )


def _home_relative(path: Path | None) -> str | None:
    """Show a path relative to the home directory, so the status names no user account.

    Args:
        path (Path | None): Configured cache directory.

    Returns:
        str | None: ``~/...`` when under the home directory, the path otherwise, or None.
    """
    if path is None:
        return None
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return path.as_posix()


def server_status(state: AppState) -> ServerStatus:
    """Describe the server's health and usage.

    Args:
        state (AppState): Server state.

    Returns:
        ServerStatus: Status document.
    """
    now = state.clock().astimezone(KST).replace(microsecond=0)
    started = _kst(state.started) or now
    info = state.directory.info()
    cache = state.cache.stats()
    components = sorted(state.metrics.components.items())
    return ServerStatus(
        as_of=now,
        version=VERSION,
        started=started,
        uptime_seconds=max(int((now - started).total_seconds()), 0),
        api_key_configured=state.gateway is not None,
        directory=DirectoryStatus(
            status=info.status,
            companies=info.companies,
            listed=info.listed,
            loaded_at=_kst(info.loaded_at),
            source=info.source,
            error=info.error,
        ),
        upstream=_upstream(state.gateway),
        response_cache=CacheStatus(
            entries=cache.entries,
            weight=cache.weight,
            max_weight=cache.max_weight,
            hits=cache.hits,
            misses=cache.misses,
        ),
        documents=state.documents.stats() if state.documents else None,
        components={key: _component(stats) for key, stats in components},
        settings=_settings(state.settings),
    )
