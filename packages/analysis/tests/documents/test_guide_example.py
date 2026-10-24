"""The package guide's first use case, run against a synthetic archive without the SDK.

``load_filing`` matches docs/documents.md; a duck-typed client stands in for ``opendart.OpenDART``.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from opendart_analysis.documents import DocumentStore, ParsedFiling, parse_filing

pytestmark = pytest.mark.anyio

FILING = "20260515003117"


class FakeDisclosures:
    """Answers ``disclosures.document`` like the SDK, from in-memory archives."""

    def __init__(self, archives: dict[str, bytes]) -> None:
        self.archives = archives
        self.calls: list[str] = []

    async def document(self, *, filing_number: str) -> bytes:
        self.calls.append(filing_number)
        return self.archives[filing_number]


class FakeClient:
    """The only part of the SDK client the example uses."""

    def __init__(self, archives: dict[str, bytes]) -> None:
        self.disclosures = FakeDisclosures(archives)


async def load_filing(client: FakeClient, filing_number: str) -> ParsedFiling:
    archive = await client.disclosures.document(filing_number=filing_number)
    return await asyncio.to_thread(parse_filing, filing_number, archive)


async def test_download_parse_outline_read_and_search(periodic_archive):
    client = FakeClient({FILING: periodic_archive})
    parsed = await load_filing(client, FILING)
    assert client.disclosures.calls == [FILING]
    assert (parsed.form_code, parsed.form_name_en) == ("11013", "Quarterly Report")

    outline = parsed.outline()
    titles = {section.id: section.title_en for section in outline.sections}
    assert titles["s35"] == "2. Borrowings (Consolidated)"
    aliases = {suggested.alias: suggested.section_ids for suggested in outline.suggested_sections}
    assert aliases["consolidated_notes"] == ["D-0-3-3-0"]

    chunk = parsed.read(section="s35")
    assert chunk.content.startswith("### 2. Borrowings (Consolidated) [s35]")
    assert "Unit: KRW million, %" in chunk.content
    assert (chunk.truncated, chunk.next_offset) == (False, None)

    result = parsed.search("borrowings")
    assert [hit.section_id for hit in result.hits] == ["s35"]


async def test_the_store_waits_for_completion_by_default(periodic_archive):
    client = FakeClient({FILING: periodic_archive})

    async def fetch(filing_number: str) -> bytes:
        return await client.disclosures.document(filing_number=filing_number)

    async with DocumentStore(fetch, max_rendered_chars=10_000_000) as store:
        parsed = await store.get(FILING)
        assert await store.get(FILING) is parsed
        assert parsed.search("borrowings").total_hits == 1
    assert client.disclosures.calls == [FILING]


def test_importing_documents_loads_neither_the_sdk_nor_mcp():
    probe = """
import sys, opendart_analysis.documents
roots = {name.partition(".")[0] for name in sys.modules}
print(sorted(roots & {"opendart", "opendart_mcp", "fastmcp", "mcp", "httpx2"}))
"""
    result = subprocess.run(  # noqa: S603 - fixed probe run with this interpreter
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=30
    )
    assert result.stdout.strip() == "[]"
