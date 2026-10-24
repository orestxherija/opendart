"""DirectoryLoader: disk cache, download, refresh schedule, readiness waits, and lifecycle.

Runs without the SDK or MCP: fetch callbacks return synthetic archives built from the domain
test rows.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from opendart_analysis.directory import (
    DirectoryError,
    DirectoryLoader,
    DirectoryNotReadyError,
    LoaderConfig,
    loader as module,
)
from opendart_analysis.errors import NotConfiguredError
from packages.analysis.tests.domain.directory_data import ROWS, directory_xml, zip_members

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def archive_of(rows=ROWS):
    return zip_members({"CORPCODE.xml": directory_xml(rows)})


def config(tmp_path, **overrides):
    return LoaderConfig(cache_path=tmp_path / "corpcode.zip", **overrides)


def fetcher(archive=None):
    calls = []

    async def fetch():
        calls.append(1)
        return archive if archive is not None else archive_of()

    fetch.calls = calls
    return fetch


def gated(gate, archive=None):
    calls = []

    async def fetch():
        calls.append(1)
        await gate.wait()
        return archive if archive is not None else archive_of()

    fetch.calls = calls
    return fetch


def age_file(path, seconds):
    moment = time.time() - seconds
    os.utime(path, (moment, moment))
    return datetime.fromtimestamp(moment, UTC)


async def test_nothing_runs_until_the_loader_is_started(tmp_path):
    fetch = fetcher()
    loader = DirectoryLoader(fetch, config(tmp_path))
    await asyncio.sleep(0.05)
    assert (fetch.calls, loader.status, loader.directory) == ([], "loading", None)
    assert not (tmp_path / "corpcode.zip").exists()
    async with loader:
        directory = await loader.wait(2)
    assert len(directory) == len(ROWS)
    assert fetch.calls == [1]


async def test_a_loader_can_be_created_outside_an_event_loop(tmp_path):
    loader = await asyncio.to_thread(DirectoryLoader, fetcher(), config(tmp_path))
    async with loader:
        assert len(await loader.wait(2)) == len(ROWS)


async def test_download_is_cached_on_disk_and_reused(tmp_path):
    fetch = fetcher()
    async with DirectoryLoader(fetch, config(tmp_path)) as first:
        directory = await first.wait(2)
        assert first.source == "download"
    assert len(directory) == len(ROWS)
    assert (tmp_path / "corpcode.zip").read_bytes() == archive_of()
    assert not (tmp_path / "corpcode.tmp").exists()

    async with DirectoryLoader(fetcher(b"unused"), config(tmp_path)) as second:
        await second.wait(2)
        assert (second.status, second.source) == ("ready", "disk")
    assert fetch.calls == [1]


async def test_a_cache_file_written_by_the_mcp_server_is_read(tmp_path):
    # The MCP server's earlier releases stored the downloaded ZIP unchanged, renamed into
    # place from a temporary sibling; the modification time records the download.
    temporary = tmp_path / "corpcode.tmp"
    temporary.write_bytes(archive_of())
    temporary.replace(tmp_path / "corpcode.zip")
    downloaded = age_file(tmp_path / "corpcode.zip", 3600)
    fetch = fetcher()
    async with DirectoryLoader(fetch, config(tmp_path)) as loader:
        directory = await loader.wait(2)
        assert loader.source == "disk"
    assert directory.loaded_at == downloaded
    assert directory.get("00126380").name == "삼성전자"
    assert fetch.calls == []


async def test_stale_cache_is_served_while_a_fresh_copy_downloads(tmp_path):
    path = tmp_path / "corpcode.zip"
    path.write_bytes(archive_of(ROWS[:2]))
    age_file(path, 3 * 86400)
    gate = asyncio.Event()
    async with DirectoryLoader(gated(gate), config(tmp_path)) as loader:
        stale = await loader.wait(2)
        assert (len(stale), loader.source) == (2, "disk")
        gate.set()
        for _ in range(100):
            if loader.source == "download":
                break
            await asyncio.sleep(0.01)
        assert len(loader.directory or ()) == len(ROWS)
        assert loader.source == "download"


async def test_without_fetch_or_cache_the_loader_is_disabled(tmp_path):
    loader = DirectoryLoader(None, config(tmp_path))
    await loader.run()
    with pytest.raises(NotConfiguredError) as raised:
        await loader.wait(1)
    assert raised.value.dependency == "fetch"
    assert loader.status == "disabled"


async def test_without_fetch_even_a_stale_cache_is_used_and_run_returns(tmp_path):
    path = tmp_path / "corpcode.zip"
    path.write_bytes(archive_of())
    age_file(path, 30 * 86400)
    loader = DirectoryLoader(None, config(tmp_path))
    await asyncio.wait_for(loader.run(), 2)
    assert (loader.status, loader.source) == ("ready", "disk")


async def test_failed_download_is_recorded_and_described(tmp_path):
    error = ConnectionError("upstream down")

    async def fail():
        raise error

    loader = DirectoryLoader(fail, config(tmp_path, retry_delays_s=(60.0,)))
    async with loader:
        with pytest.raises(DirectoryNotReadyError) as raised:
            await loader.wait(1)
    assert raised.value.status == "failed"
    assert str(raised.value) == "The company directory could not be loaded (upstream down)."
    assert raised.value.failure is loader.failure
    assert (loader.failure.reason, loader.failure.error) == ("upstream down", error)
    assert loader.status == "failed"

    described = DirectoryLoader(fail, config(tmp_path), describe_error=lambda _: "HTTP 503")
    async with described:
        with pytest.raises(DirectoryNotReadyError, match=r"\(HTTP 503\)"):
            await described.wait(1)


async def test_an_unusable_archive_is_a_failure(tmp_path):
    async with DirectoryLoader(fetcher(b"not a zip"), config(tmp_path)) as loader:
        with pytest.raises(DirectoryNotReadyError, match="unreadable"):
            await loader.wait(1)
    assert isinstance(loader.failure.error, DirectoryError)
    assert not (tmp_path / "corpcode.zip").exists()


async def test_a_stalled_download_times_out(tmp_path):
    async def stalled():
        await asyncio.Event().wait()

    async with DirectoryLoader(stalled, config(tmp_path, fetch_timeout_s=0.05)) as loader:
        with pytest.raises(DirectoryNotReadyError, match=r"\(TimeoutError\)"):
            await loader.wait(1)
    assert isinstance(loader.failure.error, TimeoutError)


async def test_initial_failures_are_retried_with_backoff(tmp_path):
    outcomes = [ConnectionError("first"), archive_of()]

    async def flaky():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async with DirectoryLoader(flaky, config(tmp_path, retry_delays_s=(0.01, 60.0))) as loader:
        with pytest.raises(DirectoryNotReadyError):
            await loader.wait(1)
        for _ in range(100):
            if loader.directory is not None:
                break
            await asyncio.sleep(0.01)
        assert (loader.status, loader.failure) == ("ready", None)
    assert outcomes == []


async def test_wait_times_out_while_loading_and_reports_progress(tmp_path):
    updates = []

    async def progress(message):
        updates.append(message)

    gate = asyncio.Event()
    loader = DirectoryLoader(gated(gate), config(tmp_path, progress_every_s=0.01))
    async with loader:
        with pytest.raises(DirectoryNotReadyError) as raised:
            await loader.wait(0.1, on_progress=progress)
        assert loader.status == "loading"
    assert raised.value.status == "loading"
    assert raised.value.failure is None
    assert str(raised.value).startswith("The company directory is still loading (0 s so far)")
    assert updates
    assert updates[0] == "Loading the OpenDART company directory (0 s elapsed)"


async def test_unwritable_cache_only_disables_caching(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    loader = DirectoryLoader(fetcher(), LoaderConfig(cache_path=blocker / "corpcode.zip"))
    async with loader:
        await loader.wait(2)
        assert loader.status == "ready"


async def test_an_unreadable_cache_is_ignored(tmp_path, caplog):
    (tmp_path / "corpcode.zip").write_bytes(b"truncated")
    async with DirectoryLoader(fetcher(), config(tmp_path)) as loader:
        await loader.wait(2)
        assert loader.source == "download"
    assert "Ignoring unreadable directory cache" in caplog.text


async def test_refresh_is_scheduled_by_archive_age(tmp_path):
    loader = DirectoryLoader(fetcher(), config(tmp_path), clock=lambda: NOW)
    assert loader._next_refresh() == 3600.0  # nothing loaded yet: retry hourly
    await loader._install(archive_of(), NOW - timedelta(hours=23), "disk")
    assert loader._next_refresh() == pytest.approx(3600.0)
    await loader._install(archive_of(), NOW - timedelta(hours=30), "disk")
    assert loader._next_refresh() == 60.0
    short = DirectoryLoader(fetcher(), config(tmp_path, max_age_s=7200.0), clock=lambda: NOW)
    await short._install(archive_of(), NOW - timedelta(hours=1), "disk")
    assert short._next_refresh() == pytest.approx(3600.0)


async def test_refresh_installs_a_new_archive_and_concurrent_calls_share_it(tmp_path):
    gate = asyncio.Event()
    fetch = gated(gate)
    loader = DirectoryLoader(fetch, config(tmp_path))
    calls = [asyncio.create_task(loader.refresh()) for _ in range(3)]
    await asyncio.sleep(0.02)
    gate.set()
    assert await asyncio.gather(*calls) == [True, True, True]
    assert fetch.calls == [1]
    assert (loader.status, loader.source) == ("ready", "download")
    assert await loader.refresh()
    assert fetch.calls == [1, 1]


async def test_a_failed_refresh_keeps_serving_the_previous_directory(tmp_path):
    outcomes = [archive_of(), ConnectionError("down")]

    async def fetch():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    loader = DirectoryLoader(fetch, config(tmp_path))
    assert await loader.refresh()
    directory = loader.directory
    assert not await loader.refresh()
    assert loader.directory is directory
    assert (loader.status, loader.failure.reason) == ("ready", "down")
    assert await loader.wait(0) is directory


async def test_an_unexpected_failure_is_reported_instead_of_loading_forever(
    tmp_path, monkeypatch, caplog
):
    def broken(archive, loaded_at):
        message = "bug"
        raise ValueError(message)

    monkeypatch.setattr(module, "_build", broken)
    async with DirectoryLoader(fetcher(), config(tmp_path)) as loader:
        with pytest.raises(DirectoryNotReadyError, match="unexpected ValueError"):
            await loader.wait(1)
        assert loader.status == "failed"
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert [record.getMessage() for record in errors] == [
        "Company directory load failed unexpectedly"
    ]


async def test_aclose_cancels_the_download_and_wakes_waiters(tmp_path):
    cancelled = asyncio.Event()

    async def stalled():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    loader = DirectoryLoader(stalled, config(tmp_path))
    loader.start()
    loader.start()  # idempotent
    waiter = asyncio.create_task(loader.wait())
    await asyncio.sleep(0.02)
    await loader.aclose()
    assert cancelled.is_set()
    with pytest.raises(DirectoryNotReadyError):
        await asyncio.wait_for(waiter, 1)
    with pytest.raises(RuntimeError, match="closed"):
        loader.start()
    with pytest.raises(RuntimeError, match="closed"):
        await loader.run()


async def test_the_directory_stays_readable_after_close(tmp_path):
    async with DirectoryLoader(fetcher(), config(tmp_path)) as loader:
        directory = await loader.wait(2)
    assert loader.directory is directory
    assert await loader.wait(0) is directory


async def test_waiting_on_a_loader_never_started_fails_at_once(tmp_path):
    fetch = fetcher()
    loader = DirectoryLoader(fetch, config(tmp_path))
    with pytest.raises(RuntimeError, match="not running; call start"):
        await asyncio.wait_for(loader.wait(), 1)
    with pytest.raises(RuntimeError, match="not running"):
        await asyncio.wait_for(loader.wait(5), 1)
    assert (fetch.calls, loader.status) == ([], "loading")


async def test_a_run_task_created_just_before_waiting_counts_as_started(tmp_path):
    loader = DirectoryLoader(fetcher(), config(tmp_path))
    runner = asyncio.create_task(loader.run())
    try:
        assert len(await asyncio.wait_for(loader.wait(), 2)) == len(ROWS)
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_waiters_fail_when_a_caller_owned_run_stops_before_loading(tmp_path):
    gate = asyncio.Event()
    loader = DirectoryLoader(gated(gate), config(tmp_path, progress_every_s=0.01))
    runner = asyncio.create_task(loader.run())
    waiter = asyncio.create_task(loader.wait())
    await asyncio.sleep(0.02)
    runner.cancel()
    await asyncio.gather(runner, return_exceptions=True)
    with pytest.raises(RuntimeError, match="not running"):
        await asyncio.wait_for(waiter, 1)


async def test_run_cannot_be_started_twice(tmp_path):
    loader = DirectoryLoader(fetcher(), config(tmp_path))
    async with loader:
        await loader.wait(2)
        with pytest.raises(RuntimeError, match="already running"):
            await loader.run()


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_age_s": 0},
        {"progress_every_s": 0},
        {"fetch_timeout_s": 0},
        {"retry_delays_s": ()},
        {"retry_delays_s": (-1.0,)},
    ],
)
def test_invalid_configuration_is_rejected(overrides):
    with pytest.raises(ValueError, match=r"must|needs"):
        LoaderConfig(**overrides)


def test_defaults_cache_nothing_and_refresh_daily():
    defaults = LoaderConfig()
    assert (defaults.cache_path, defaults.max_age_s, defaults.fetch_timeout_s) == (
        None,
        86_400.0,
        900.0,
    )
    assert defaults.retry_delays_s == (60.0, 300.0, 900.0, 3600.0)
