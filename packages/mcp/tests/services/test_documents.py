"""Document service internals: failure translation, waits, and the store call."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opendart import ResponseTooLargeError, UnavailableError
from opendart_mcp.core.errors import InvalidArgumentError, StillRunningError, UpstreamError
from opendart_mcp.documents import DocumentError, DownloadPendingError, StoreClosedError
from opendart_mcp.services.documents import (
    BACKGROUND_WAIT_S,
    FOREGROUND_WAIT_S,
    DocumentUnavailableError,
    _failure,
    load_filing,
    wait_seconds,
)
from opendart_mcp.settings import DocumentSettings, Settings

NUMBER = "20261022000123"
VIEWER = f"https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo={NUMBER}"


@pytest.mark.parametrize(
    ("error", "kind", "text"),
    [
        (DownloadPendingError(NUMBER, 40.0), StillRunningError, "Repeat the same call"),
        (TimeoutError(), UpstreamError, "took over two minutes"),
        (
            ResponseTooLargeError("too big", operation="/document.xml"),
            DocumentUnavailableError,
            f"larger than this server downloads (32 MiB compressed). Open it in the DART viewer: {VIEWER}",
        ),
        (StoreClosedError("closed"), UpstreamError, "shutting down"),
        (
            DocumentError("odd"),
            DocumentUnavailableError,
            f"(DocumentError). Open it in the DART viewer: {VIEWER}",
        ),
        (UnavailableError("down", operation="/document.xml"), UpstreamError, "did not respond"),
    ],
)
def test_failures_become_instructions(error, kind, text):
    translated = _failure(error, NUMBER)
    assert type(translated) is kind
    assert text in str(translated)


def test_waits_depend_on_the_execution_mode():
    state = SimpleNamespace(settings=Settings())
    assert wait_seconds(state, background=True) == BACKGROUND_WAIT_S
    assert wait_seconds(state, background=False) == FOREGROUND_WAIT_S
    short = SimpleNamespace(settings=Settings(documents=DocumentSettings(wait=3)))
    assert wait_seconds(short, background=False) == 3


class RecordingStore:
    def __init__(self):
        self.calls = []

    async def get(self, filing_number, *, wait_s, on_progress=None):
        self.calls.append((filing_number, wait_s))
        await on_progress("Downloading")
        return "parsed"


@pytest.mark.anyio
async def test_load_filing_passes_the_wait_and_progress_to_the_store():
    store = RecordingStore()
    messages = []

    async def progress(message):
        messages.append(message)

    state = SimpleNamespace(require_documents=lambda: store)
    assert await load_filing(state, NUMBER, wait_s=12.5, progress=progress) == "parsed"
    assert store.calls == [(NUMBER, 12.5)]
    assert messages == ["Downloading"]


@pytest.mark.anyio
async def test_load_filing_rejects_malformed_numbers_before_the_store():
    store = RecordingStore()
    state = SimpleNamespace(require_documents=lambda: store)
    with pytest.raises(InvalidArgumentError, match="'2026-10-22' is not a filing number"):
        await load_filing(state, "2026-10-22", wait_s=1)
    assert store.calls == []
