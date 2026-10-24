"""The public directory API, used the way the package guide shows, without the SDK or MCP.

``load_directory`` matches docs/directory.md; a duck-typed client stands in for ``opendart.OpenDART``
and answers ``disclosures.corporation_codes`` with a synthetic archive built from the domain
test rows.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from opendart_analysis.directory import (
    CANDIDATE_POOL,
    MAX_EXPANDED_BYTES,
    CorpRecord,
    Directory,
    DirectoryError,
    Match,
    Resolution,
    company_label,
    parse_directory,
    resolve,
)
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
    """The only part of the SDK client the example uses."""

    def __init__(self, archive: bytes) -> None:
        self.disclosures = FakeDisclosures(archive)


async def load_directory(client: FakeClient) -> Directory:
    archive = await client.disclosures.corporation_codes()
    loaded_at = datetime.now(UTC)
    records = await asyncio.to_thread(parse_directory, archive)
    return Directory.build(records, loaded_at=loaded_at)


@pytest.fixture
def archive() -> bytes:
    return zip_members({"CORPCODE.xml": directory_xml(ROWS)})


@pytest.fixture
def directory(archive: bytes) -> Directory:
    return Directory.build(parse_directory(archive), loaded_at=datetime(2026, 10, 22, tzinfo=UTC))


async def test_download_parse_and_resolve(archive):
    client = FakeClient(archive)
    directory = await load_directory(client)
    assert client.disclosures.calls == 1
    assert len(directory) == len(ROWS)

    resolution = resolve(directory, "Samsung Electronics")
    assert isinstance(resolution, Resolution)
    assert (resolution.reason, resolution.record.corp_code) == ("exact", "00126380")


@pytest.mark.parametrize(
    ("text", "corp_code"),
    [
        ("SAMSUNG ELECTRONICS CO,.LTD", "00126380"),
        ("삼성전자", "00126380"),
        ("SK hynix", "00164779"),
        ("카카오", "00258801"),
        ("LG Energy", "01515323"),
    ],
)
def test_names_resolve_in_english_and_korean(directory, text, corp_code):
    resolution = resolve(directory, text)
    assert resolution.reason in {"exact", "dominant"}
    assert resolution.record.corp_code == corp_code


@pytest.mark.parametrize(
    ("text", "corp_code"),
    [
        ("005930", "00126380"),
        ("A005930", "00126380"),
        ("0068Y0", "01933981"),
        ("00126380", "00126380"),
    ],
)
def test_codes_resolve_exactly(directory, text, corp_code):
    resolution = resolve(directory, text)
    assert resolution.reason == "code"
    assert resolution.record.corp_code == corp_code
    assert [match.tier for match in resolution.candidates] == ["code"]


def test_an_ambiguous_name_returns_ranked_candidates(directory):
    resolution = resolve(directory, "Samsung")
    assert (resolution.reason, resolution.record) == ("ambiguous", None)
    assert 5 < len(resolution.candidates) <= CANDIDATE_POOL
    assert all(isinstance(match, Match) for match in resolution.candidates)
    listed = [match.record.listed for match in resolution.candidates]
    assert listed == sorted(listed, reverse=True)
    assert resolution.candidates[0].record.corp_code == "00149655"
    assert company_label(resolution.candidates[0].record) == (
        "SAMSUNG C&T CORPORATION (삼성물산; corp 00149655, stock 028260, modified 2026-03-23)"
    )


@pytest.mark.parametrize("text", ["Acme Widgets", "999999", "12345678", "20250314000123"])
def test_a_missing_reference_is_not_found(directory, text):
    resolution = resolve(directory, text)
    assert (resolution.reason, resolution.record, resolution.candidates) == ("not_found", None, ())


def test_search_get_and_stock_lookups(directory):
    matches = directory.search("Kakao", listed=True, limit=3)
    assert [match.record.corp_code for match in matches] == ["00258801", "01133217", "01137383"]
    assert [match.tier for match in matches] == ["exact", "prefix", "prefix"]
    assert directory.get("00126380") == directory.by_stock_code("005930")
    record = directory.get("09000002")
    assert record == CorpRecord("09000002", "다코", None, None, None)
    assert not record.listed


def test_malformed_archives_raise_directory_error():
    with pytest.raises(DirectoryError, match="unreadable"):
        parse_directory(b"not a zip")
    with pytest.raises(DirectoryError, match="over the 10-byte limit"):
        parse_directory(zip_members({"CORPCODE.xml": directory_xml(ROWS)}), max_expanded_bytes=10)
    assert MAX_EXPANDED_BYTES == 64 * 2**20


def test_importing_the_directory_loads_neither_the_sdk_nor_mcp():
    probe = """
import sys, opendart_analysis.directory
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "httpx2", "anyio"}))
"""
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=30
    )
    assert result.stdout.strip() == "[]"
