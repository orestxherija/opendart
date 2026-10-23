"""Company directory loading: disk cache, download, refresh, and readiness waits."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import anyio
import pytest

from opendart import UnavailableError
from opendart_mcp.core.errors import (
    API_KEY_MISSING,
    ConfigurationError,
    DirectoryUnavailableError,
    UpstreamError,
)
from opendart_mcp.services import directory as module
from opendart_mcp.services.directory import ARCHIVE_NAME, DirectoryService
from opendart_mcp.settings import DirectorySettings


def settings(tmp_path, **overrides):
    return DirectorySettings(cache_dir=tmp_path, wait=0.5, **overrides)


def fetcher(upstream, archive=None):
    calls = []

    async def fetch():
        calls.append(1)
        return archive if archive is not None else upstream.corp_archive()

    fetch.calls = calls
    return fetch


async def start(service, tg):
    tg.start_soon(service.run)
    return await service.wait(2)


@pytest.mark.anyio
async def test_without_key_or_cache_the_directory_is_disabled(tmp_path):
    service = DirectoryService(None, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(ConfigurationError) as raised:
            await service.wait(1)
    assert str(raised.value) == API_KEY_MISSING
    assert service.info().status == "disabled"


@pytest.mark.anyio
async def test_download_is_cached_on_disk_and_reused(tmp_path, upstream):
    fetch = fetcher(upstream)
    first = DirectoryService(fetch, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        directory = await start(first, tg)
        tg.cancel_scope.cancel()
    assert len(directory) == len(upstream.companies)
    assert (tmp_path / ARCHIVE_NAME).is_file()
    assert first.info().source == "download"

    second = DirectoryService(fetcher(upstream, b"unused"), settings(tmp_path))
    async with anyio.create_task_group() as tg:
        await start(second, tg)
        tg.cancel_scope.cancel()
    info = second.info()
    assert (info.status, info.source, info.listed) == ("ready", "disk", 12)
    assert fetch.calls == [1]


@pytest.mark.anyio
async def test_stale_cache_is_served_while_a_fresh_copy_downloads(tmp_path, upstream):
    path = tmp_path / ARCHIVE_NAME
    path.write_bytes(upstream.corp_archive(upstream.companies[:2]))
    old = time.time() - 3 * 86400
    os.utime(path, (old, old))
    service = DirectoryService(fetcher(upstream), settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()
    assert len(service.directory or ()) == 14
    assert service.info().source == "download"


@pytest.mark.anyio
async def test_failed_download_reports_retrying(tmp_path):
    async def fail():
        raise UpstreamError("OpenDART did not respond")

    service = DirectoryService(fail, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError, match="could not be loaded"):
            await service.wait(1)
        tg.cancel_scope.cancel()
    assert service.info().status == "failed"


@pytest.mark.anyio
async def test_wait_times_out_while_loading_and_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_PROGRESS_INTERVAL", 0.01)
    gate = anyio.Event()

    async def slow():
        await gate.wait()
        return b""

    updates = []

    async def progress(message):
        updates.append(message)

    service = DirectoryService(slow, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError, match="still loading"):
            await service.wait(0.1, progress)
        tg.cancel_scope.cancel()
    assert updates
    assert service.info().status == "loading"


@pytest.mark.anyio
async def test_unwritable_cache_only_disables_caching(tmp_path, upstream):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    service = DirectoryService(fetcher(upstream), DirectorySettings(cache_dir=blocker, wait=1))
    async with anyio.create_task_group() as tg:
        await start(service, tg)
        tg.cancel_scope.cancel()
    assert service.info().status == "ready"


@pytest.mark.anyio
async def test_refresh_is_scheduled_by_archive_age(tmp_path, upstream):
    now = datetime(2026, 10, 22, tzinfo=UTC)
    service = DirectoryService(fetcher(upstream), settings(tmp_path), clock=lambda: now)
    assert service._next_refresh() == 3600.0  # nothing loaded yet: retry hourly
    await service._install(upstream.corp_archive(), now - timedelta(hours=23), "disk")
    assert service._next_refresh() == pytest.approx(3600.0)
    await service._install(upstream.corp_archive(), now - timedelta(hours=30), "disk")
    assert service._next_refresh() == 60.0


@pytest.mark.anyio
async def test_sdk_failures_are_translated_and_retried_later(tmp_path):
    async def unavailable():
        raise UnavailableError(
            "OpenDART is unavailable", operation="/corpCode.xml", http_status=503
        )

    service = DirectoryService(unavailable, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError, match="did not respond after one retry"):
            await service.wait(1)
        tg.cancel_scope.cancel()
    assert service.info().status == "failed"


@pytest.mark.anyio
async def test_an_unexpected_failure_is_reported_instead_of_loading_forever(
    tmp_path, upstream, monkeypatch
):
    def broken(archive, loaded_at):
        message = "bug"
        raise ValueError(message)

    monkeypatch.setattr(module, "_build", broken)
    service = DirectoryService(fetcher(upstream), settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError, match="unexpected ValueError"):
            await service.wait(1)
        tg.cancel_scope.cancel()
    assert service.info().status == "failed"
