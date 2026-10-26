"""Company directory adapter: settings, disk cache location, and the server's messages.

The loading, caching, and refresh behavior itself is tested with the analysis loader in
packages/analysis/tests/directory/test_loader.py.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

import anyio
import pytest

from opendart import UnavailableError
from opendart_analysis.directory import loader as loader_module
from opendart_mcp.core.errors import (
    API_KEY_MISSING,
    ConfigurationError,
    DirectoryUnavailableError,
    UpstreamError,
)
from opendart_mcp.services import directory as module
from opendart_mcp.services.directory import ARCHIVE_NAME, DirectoryService, loader_config
from opendart_mcp.settings import DirectorySettings, default_cache_dir

HINT = "Meanwhile, pass an 8-digit DART corp code, which works without the directory."


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


def test_settings_keep_the_cache_location_schedule_and_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    config = loader_config(DirectorySettings())
    assert config.cache_path == default_cache_dir() / "corpcode.zip"
    assert config.cache_path == tmp_path / "opendart-mcp" / "corpcode.zip"
    assert (config.max_age_s, config.fetch_timeout_s) == (86_400.0, 900.0)
    assert config.retry_delays_s == (60.0, 300.0, 900.0, 3600.0)
    assert config.progress_every_s == 5.0
    custom = loader_config(DirectorySettings(cache_dir=None, max_age_hours=2, deadline=30))
    assert (custom.cache_path, custom.max_age_s, custom.fetch_timeout_s) == (None, 7200.0, 30.0)


@pytest.mark.anyio
async def test_without_key_or_cache_the_directory_is_disabled(tmp_path):
    service = DirectoryService(None, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(ConfigurationError) as raised:
            await service.wait(1)
    assert str(raised.value) == API_KEY_MISSING
    assert raised.value.__context__ is None
    assert service.info().status == "disabled"


@pytest.mark.anyio
async def test_download_is_cached_on_disk_and_reused(tmp_path, upstream):
    fetch = fetcher(upstream)
    first = DirectoryService(fetch, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        directory = await start(first, tg)
        tg.cancel_scope.cancel()
    assert len(directory) == len(upstream.companies)
    assert (tmp_path / ARCHIVE_NAME).read_bytes() == upstream.corp_archive()
    assert first.info().source == "download"

    second = DirectoryService(fetcher(upstream, b"unused"), settings(tmp_path))
    async with anyio.create_task_group() as tg:
        await start(second, tg)
        tg.cancel_scope.cancel()
    info = second.info()
    assert (info.status, info.source, info.listed) == ("ready", "disk", 12)
    assert fetch.calls == [1]


@pytest.mark.anyio
async def test_a_cache_file_from_earlier_releases_is_read_without_downloading(tmp_path, upstream):
    # Earlier releases wrote the downloaded ZIP unchanged to <cache_dir>/corpcode.zip through
    # a temporary sibling and a rename; its modification time is the download time.
    temporary = tmp_path / "corpcode.tmp"
    temporary.write_bytes(upstream.corp_archive())
    temporary.replace(tmp_path / "corpcode.zip")
    downloaded = time.time() - 3600
    os.utime(tmp_path / "corpcode.zip", (downloaded, downloaded))
    fetch = fetcher(upstream)
    service = DirectoryService(fetch, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        directory = await start(service, tg)
        tg.cancel_scope.cancel()
    info = service.info()
    assert (info.status, info.source, info.companies) == ("ready", "disk", 14)
    assert directory.loaded_at == datetime.fromtimestamp(downloaded, UTC)
    assert fetch.calls == []


@pytest.mark.anyio
async def test_failed_download_reports_retrying(tmp_path):
    async def fail():
        raise UpstreamError("OpenDART did not respond")

    service = DirectoryService(fail, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError) as raised:
            await service.wait(1)
        tg.cancel_scope.cancel()
    assert str(raised.value) == (
        "The company directory could not be loaded (OpenDART did not respond); the server is"
        + " retrying in the background. "
        + HINT
    )
    info = service.info()
    assert (info.status, info.error) == ("failed", "OpenDART did not respond")


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

    now = datetime(2026, 10, 22, tzinfo=UTC)
    service = DirectoryService(slow, settings(tmp_path), clock=lambda: now)
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError) as raised:
            await service.wait(0.1, progress)
        tg.cancel_scope.cancel()
    assert str(raised.value) == (
        "The company directory is still loading (0 s so far; OpenDART can take several"
        + " minutes). Retry shortly. "
        + HINT
    )
    assert updates
    assert updates[0] == "Loading the OpenDART company directory (0 s elapsed)"
    assert service.info().status == "loading"


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

    monkeypatch.setattr(loader_module, "_build", broken)
    service = DirectoryService(fetcher(upstream), settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError, match="unexpected ValueError"):
            await service.wait(1)
        tg.cancel_scope.cancel()
    assert service.info().status == "failed"


@pytest.mark.anyio
async def test_an_unexpected_download_error_is_logged_and_named_by_type(tmp_path, caplog):
    async def broken():
        message = "secret detail"
        raise RuntimeError(message)

    service = DirectoryService(broken, settings(tmp_path))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError, match=r"\(unexpected RuntimeError\)"):
            await service.wait(1)
        tg.cancel_scope.cancel()
    assert service.info().error == "unexpected RuntimeError"
    logged = [record for record in caplog.records if record.exc_info]
    assert [record.getMessage() for record in logged] == [
        "Company directory load failed unexpectedly"
    ]


@pytest.mark.anyio
async def test_a_download_timeout_is_named(tmp_path):
    async def stalled():
        await anyio.sleep_forever()

    service = DirectoryService(stalled, settings(tmp_path, deadline=0.05))
    async with anyio.create_task_group() as tg:
        tg.start_soon(service.run)
        with pytest.raises(DirectoryUnavailableError, match=r"\(TimeoutError\)"):
            await service.wait(1)
        tg.cancel_scope.cancel()
