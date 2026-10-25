"""The directory guide's loader recipe, run with a duck-typed client instead of the SDK.

``sdk_archive_fetch`` and ``run_example`` match the Loader section of docs/directory.md; the
fake client answers ``disclosures.corporation_codes`` with a synthetic archive.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Self

import pytest

from opendart_analysis.directory import DirectoryLoader, FetchArchive, LoaderConfig, resolve
from packages.analysis.tests.domain.directory_data import ROWS, directory_xml, zip_members

pytestmark = pytest.mark.anyio


class FakeDisclosures:
    """Answers ``disclosures.corporation_codes`` like the SDK, from one in-memory archive."""

    def __init__(self, archive: bytes) -> None:
        self.archive = archive
        self.calls = 0

    async def corporation_codes(self) -> bytes:
        self.calls += 1
        return self.archive


class FakeClient:
    """The only part of the SDK client the recipe uses; also an async context manager."""

    def __init__(self, archive: bytes) -> None:
        self.disclosures = FakeDisclosures(archive)
        self.closed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.closed = True


def sdk_archive_fetch(client: FakeClient) -> FetchArchive:
    async def fetch_archive() -> bytes:
        return await client.disclosures.corporation_codes()

    return fetch_archive


async def run_example(client: FakeClient, config: LoaderConfig) -> str:
    async with client, DirectoryLoader(sdk_archive_fetch(client), config) as loader:
        directory = await loader.wait(600)
        return resolve(directory, "Samsung Electronics").reason


@pytest.fixture
def archive() -> bytes:
    return zip_members({"CORPCODE.xml": directory_xml(ROWS)})


async def test_the_recipe_downloads_once_then_restarts_from_the_cache(tmp_path, archive):
    config = LoaderConfig(cache_path=tmp_path / "my-app" / "corpcode.zip")
    client = FakeClient(archive)
    assert await run_example(client, config) == "exact"
    assert (client.disclosures.calls, client.closed) == (1, True)
    assert config.cache_path.read_bytes() == archive

    restarted = FakeClient(archive)
    assert await run_example(restarted, config) == "exact"
    assert restarted.disclosures.calls == 0


def test_importing_and_constructing_a_loader_starts_nothing():
    probe = """
import sys, threading
from opendart_analysis.directory import DirectoryLoader, LoaderConfig

async def fetch():
    raise AssertionError("fetched")

loader = DirectoryLoader(fetch, LoaderConfig())
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "anyio"}), threading.active_count(), loader.status)
"""
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=30
    )
    assert result.stdout.strip() == "[] 1 loading"
