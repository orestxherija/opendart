"""Single-attempt transfers; install as app.http_streaming.

The caller owns the existing client and async destination. ``upload_from``
takes ownership of its async generator, including closing it on failure.
Use cancellation-cooperative sources/sinks and client per-phase timeouts;
wrap either call in ``asyncio.timeout`` for an overall deadline.

Neither helper accumulates a body. Download chunks are bounded at the sink,
and upload sources must yield bounded chunks. Transport and sink buffers are
separate from these bounds. Partial destination data is the caller's concern.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing

import httpx2


class TransferLimitError(ValueError):
    """A transfer exceeded its total-size or source-chunk budget."""


def _check_limits(max_bytes: int, chunk_size: int) -> None:
    for name, value in (("max_bytes", max_bytes), ("chunk_size", chunk_size)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")


async def download_into(
    client: httpx2.AsyncClient,
    url: str,
    write: Callable[[bytes], Awaitable[None]],
    *,
    max_bytes: int,
    chunk_size: int = 64 * 1024,
) -> int:
    """Download identity-encoded bytes to an async sink; return bytes written.

    The response is closed on success, HTTP failure, sink failure, and
    cancellation. The sink remains caller-owned and may contain partial data.
    Compressed responses are rejected before reading their bodies to avoid
    unbounded decompression inside the HTTP client's decoder.
    """
    _check_limits(max_bytes, chunk_size)
    total = 0
    async with client.stream(
        "GET", url, headers={"Accept-Encoding": "identity"}, follow_redirects=False
    ) as response:
        response.raise_for_status()
        encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
        if encoding != "identity":
            raise ValueError("download requires identity content encoding")
        async for chunk in response.aiter_raw(chunk_size):
            if total + len(chunk) > max_bytes:
                raise TransferLimitError("download exceeds max_bytes")
            await write(chunk)
            total += len(chunk)
    return total


async def upload_from(
    client: httpx2.AsyncClient,
    url: str,
    source: AsyncGenerator[bytes, None],
    *,
    max_bytes: int,
    chunk_size: int = 64 * 1024,
) -> int:
    """PUT a one-shot body and return status without buffering the response.

    Closes the source generator even when validation or sending fails. The
    caller must supply a bounded source, and auth must not buffer or replay it.
    Redirects are disabled. A retry requires a newly opened source plus the
    upstream's documented replay/idempotency contract.
    """
    async with aclosing(source):
        _check_limits(max_bytes, chunk_size)

        async def chunks() -> AsyncGenerator[bytes, None]:
            total = 0
            async for chunk in source:
                if len(chunk) > chunk_size:
                    raise TransferLimitError("upload source chunk exceeds chunk_size")
                total += len(chunk)
                if total > max_bytes:
                    raise TransferLimitError("upload exceeds max_bytes")
                yield chunk

        async with (
            aclosing(chunks()) as content,
            client.stream(
                "PUT",
                url,
                content=content,
                headers={"Content-Type": "application/octet-stream"},
                follow_redirects=False,
            ) as response,
        ):
            response.raise_for_status()
            return response.status_code
