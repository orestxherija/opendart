"""Verify SDK error translation, request validation, bounded reads, and cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx2
import pytest
from pydantic import ValidationError

from opendart import (
    APIError,
    APIRejectedError,
    ContractError,
    FileUnavailableError,
    NoDataError,
    OpenDART,
    QuotaExceededError,
    RejectedError,
    ResponseTooLargeError,
    ServiceUnavailableError,
    UnavailableError,
)

pytestmark = pytest.mark.anyio


class TrackedTransport(httpx2.AsyncBaseTransport):
    """Record requests and ownership cleanup for an injected async transport."""

    def __init__(self):
        """Initialize request history and closure tracking."""
        self.requests = []
        self.closed = False

    async def handle_async_request(self, request):
        """Record a request and return a successful synthetic envelope.

        Args:
            request (httpx2.Request): Outgoing SDK request.

        Returns:
            httpx2.Response: Successful synthetic response.
        """
        self.requests.append(request)
        return httpx2.Response(200, json={"status": "000", "message": "OK"})

    async def aclose(self):
        """Record that the owning SDK client released this transport."""
        self.closed = True


@pytest.mark.parametrize("context_manager", [False, True])
async def test_client_owns_transport_and_rejects_calls_after_close(settings, context_manager):
    """Verify shared transport ownership and both supported cleanup paths.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        context_manager (bool): Close through async context exit instead of explicit aclose.
    """
    transport = TrackedTransport()
    client = OpenDART(settings, transport=transport)
    if context_manager:
        with pytest.raises(ValueError, match="context failure"):
            async with client:
                await client.disclosures.search()
                await client.disclosures.company(corporation_code="00126380")
                raise ValueError("context failure")
    else:
        try:
            await client.disclosures.search()
            await client.disclosures.company(corporation_code="00126380")
        finally:
            await client.aclose()
    assert client.is_closed
    assert transport.closed
    assert len(transport.requests) == 2
    with pytest.raises(RuntimeError):
        await client.disclosures.search()
    assert len(transport.requests) == 2


async def test_shared_client_allows_concurrent_requests(settings):
    """Verify requests on separate resources can make progress concurrently.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
    """
    requests = []
    both_started = asyncio.Event()

    async def handler(request):
        """Wait until both requests arrive before returning a successful envelope.

        Args:
            request (httpx2.Request): Outgoing SDK request.

        Returns:
            httpx2.Response: Successful synthetic response.
        """
        requests.append(request)
        if len(requests) == 2:
            both_started.set()
        await both_started.wait()
        return httpx2.Response(200, json={"status": "000", "message": "OK"})

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        async with asyncio.timeout(2):
            results = await asyncio.gather(
                client.disclosures.search(),
                client.financial_statements.fnltt_singl_acnt(
                    corporation_code="00126380", fiscal_year="2025", report_period="11011"
                ),
            )
    assert len(requests) == 2
    assert all(result.status == "000" for result in results)
    assert client.is_closed


@pytest.mark.parametrize(
    "status,kind",
    [
        ("010", APIRejectedError),
        ("011", APIRejectedError),
        ("012", APIRejectedError),
        ("013", NoDataError),
        ("014", FileUnavailableError),
        ("020", QuotaExceededError),
        ("021", APIRejectedError),
        ("100", APIRejectedError),
        ("101", APIRejectedError),
        ("800", ServiceUnavailableError),
        ("900", APIError),
        ("901", APIRejectedError),
        ("999", APIError),
    ],
)
@pytest.mark.parametrize("archive", [False, True])
async def test_application_errors(settings, status, kind, archive):
    """Verify application status translation, credential redaction, and one attempt.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        status (str): Synthetic three-digit application status.
        kind (type[OpenDARTError]): Expected SDK exception class.
        archive (bool): Whether to exercise the archive endpoint instead of JSON.
    """
    calls = []
    key = settings.api_key.get_secret_value()

    def handler(request):
        """Record the request and return the configured synthetic error response.

        Args:
            request (httpx2.Request): Outgoing request to record.

        Returns:
            httpx2.Response: Synthetic error response for this test case.
        """
        calls.append(request)
        if archive:
            return httpx2.Response(
                200,
                content=f"<result><status>{status}</status><message>{key}</message></result>".encode(),
            )
        return httpx2.Response(200, json={"status": status, "message": key})

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(kind) as caught:
            if archive:
                await client.disclosures.corporation_codes()
            else:
                await client.disclosures.search()
    assert caught.value.status == status
    assert key not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,kind",
    [
        (301, ContractError),
        (302, ContractError),
        (400, RejectedError),
        (401, RejectedError),
        (403, RejectedError),
        (404, RejectedError),
        (429, UnavailableError),
        (500, UnavailableError),
        (503, UnavailableError),
    ],
)
async def test_http_failures_do_not_follow_redirects_or_retry(settings, status, kind):
    """Verify HTTP error translation without redirects or repeated requests.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        status (int): Synthetic HTTP response status.
        kind (type[OpenDARTError]): Expected SDK exception class.
    """
    calls = []

    def handler(request):
        """Record the request and return the configured synthetic error response.

        Args:
            request (httpx2.Request): Outgoing request to record.

        Returns:
            httpx2.Response: Synthetic error response for this test case.
        """
        calls.append(request)
        return httpx2.Response(status, headers={"Location": "https://elsewhere.example/"})

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(kind) as caught:
            await client.disclosures.search()
    assert caught.value.http_status == status
    assert len(calls) == 1
    assert settings.api_key.get_secret_value() not in str(caught.value)


@pytest.mark.parametrize(
    "failure", [httpx2.ConnectError, httpx2.ReadTimeout, httpx2.RemoteProtocolError]
)
async def test_transport_failures(settings, failure):
    """Verify transport failures retain their cause behind a safe SDK exception.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        failure (type[httpx2.RequestError]): HTTP exception class raised by the mock
            handler.
    """

    def handler(request):
        """Raise the configured transport failure for an outgoing request.

        Args:
            request (httpx2.Request): Request attached to the synthetic failure.

        Raises:
            httpx2.RequestError: Always, using the parametrized HTTP exception class.
        """
        raise failure("Synthetic failure", request=request)

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(UnavailableError) as caught:
            await client.disclosures.search()
    assert isinstance(caught.value.__cause__, failure)


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b"null",
        b"[]",
        b"{}",
        b'{"status":0,"message":"wrong type"}',
        b'{"status":"000","message":"OK","list":"wrong type"}',
        b'{"status":"00","message":"wrong code"}',
    ],
)
async def test_unexpected_json_is_contract_failure(settings, body):
    """Verify malformed JSON or response shapes raise ContractError.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        body (bytes): Invalid synthetic JSON response body.
    """
    async with OpenDART(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, content=body))
    ) as client:
        with pytest.raises(ContractError):
            await client.disclosures.search()


@pytest.mark.parametrize(
    "body",
    [
        b"not a zip",
        b"<wrong/>",
        b"<result><status>000</status><message>OK</message></result>",
        b'<!DOCTYPE result [<!ENTITY injected "013">]><result><status>&injected;</status><message>bad</message></result>',
    ],
)
async def test_unexpected_downloads_and_xml_entities(settings, body):
    """Verify invalid archives and unsafe XML are rejected as contract failures.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        body (bytes): Malformed archive or unsafe XML response body.
    """
    async with OpenDART(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, content=body))
    ) as client:
        with pytest.raises(ContractError):
            await client.disclosures.corporation_codes()


@pytest.mark.parametrize(
    "params",
    [
        {"corporation_code": "123"},
        {"corporation_code": "https://example.com"},
        {"page_size": 101},
        {"page_number": 0},
        {"page_number": True},
        {"page_number": "1"},
        {"sort_by": "invalid"},
        {"filing_start_date": "2025-01-01"},
    ],
)
async def test_invalid_requests_never_reach_transport(settings, params):
    """Verify invalid query fields fail validation before any HTTP call.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        params (dict[str, object]): Invalid query fields to pass to disclosure search.
    """

    def handler(_):
        """Fail if invalid query data reaches the HTTP transport.

        Args:
            _ (httpx2.Request): Unexpected outgoing request.

        Raises:
            pytest.fail.Exception: Always, because validation should have rejected the request.
        """
        pytest.fail("Invalid parameters reached the transport")

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(ValidationError):
            await client.disclosures.search(**params)


@pytest.mark.parametrize("codes", [[], ["00126380"] * 101, ["invalid"]])
async def test_batch_bounds(settings, codes):
    """Verify empty, oversized, and malformed corporation-code batches are rejected.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        codes (list[str]): Invalid corporation-code batch.
    """

    def handler(_):
        """Fail if invalid query data reaches the HTTP transport.

        Args:
            _ (httpx2.Request): Unexpected outgoing request.

        Raises:
            pytest.fail.Exception: Always, because validation should have rejected the request.
        """
        pytest.fail("Invalid batch reached the transport")

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(ValidationError):
            await client.financial_statements.fnltt_multi_acnt(
                corporation_codes=codes, fiscal_year="2025", report_period="11011"
            )


async def test_missing_optional_fields_unknown_fields_and_raw_amounts(settings):
    """Verify optional omissions, upstream extensions, and financial text survive parsing.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
    """
    body = {
        "status": "000",
        "message": "OK",
        "new_root": True,
        "list": [{"thstrm_amount": "1,234", "new_field": "-"}],
    }
    async with OpenDART(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        result = await client.financial_statements.fnltt_singl_acnt(
            corporation_code="00126380", fiscal_year="2025", report_period="11011"
        )
    assert result.list[0].current_period_amount == "1,234"
    assert result.model_dump(exclude_unset=True, by_alias=True) == body


async def test_encoded_body_rejected_before_consuming(settings):
    """Verify non-identity encoding is rejected before reading the response body.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
    """
    stream = FiniteStream(False)
    async with OpenDART(
        settings,
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(200, stream=stream, headers={"Content-Encoding": "gzip"})
        ),
    ) as client:
        with pytest.raises(ContractError, match="identity"):
            await client.disclosures.search()
    assert stream.closed
    assert not stream.started


class FiniteStream(httpx2.AsyncByteStream):
    """Yield finite async test chunks with optional failure and cleanup tracking.

    Attributes:
        closed (bool): Whether aclose() was called.
        failure (bool): Whether iteration raises after the first chunk.
        started (bool): Whether response iteration began.
    """

    def __init__(self, failure):
        """Initialize the finite asynchronous test stream.

        Args:
            failure (bool): Whether the synthetic stream should fail after its first chunk.
        """
        self.closed = False
        self.failure = failure
        self.started = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield two async chunks, optionally failing between them.

        Yields:
            bytes: A 64 KiB chunk of synthetic content.

        Raises:
            httpx2.ReadError: The stream was configured to fail after the first chunk.
        """
        self.started = True
        yield b"x" * 64 * 1024
        if self.failure:
            raise httpx2.ReadError("body interrupted")
        yield b"x" * 64 * 1024

    async def aclose(self):
        """Record that the finite async response stream has been closed."""
        self.closed = True


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("archive", [False, True])
async def test_stream_failure_and_size_limit(settings, failure, archive):
    """Verify async JSON and archive streams close on read failures and size limits.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        failure (bool): Whether the synthetic stream should fail after its first chunk.
        archive (bool): Whether to exercise the archive endpoint instead of JSON.
    """
    stream = FiniteStream(failure)
    configured = settings.model_copy(
        update={"max_response_bytes": 100000, "max_download_bytes": 100000}
    )
    async with OpenDART(
        configured, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, stream=stream))
    ) as client:
        with pytest.raises(UnavailableError if failure else ResponseTooLargeError):
            if archive:
                await client.disclosures.corporation_codes()
            else:
                await client.disclosures.search()
        assert stream.closed
    assert client.is_closed


class TrackedStream(httpx2.AsyncByteStream):
    """Pause an async response after signaling that the second read has started.

    Attributes:
        started (asyncio.Event): Set when iteration reaches the blocking read.
        closed (bool): Whether aclose() was called.
    """

    def __init__(self):
        """Initialize cancellation synchronization and response cleanup tracking."""
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield an initial chunk, signal the next read, and block until cancelled.

        Yields:
            bytes: The initial synthetic body chunk.

        Raises:
            asyncio.CancelledError: The task is cancelled while the stream waits.
        """
        yield b"start"
        self.started.set()
        await asyncio.Event().wait()

    async def aclose(self):
        """Record that the blocking async response stream has been closed."""
        self.closed = True


@pytest.mark.parametrize("archive", [False, True])
async def test_cancellation_propagates_and_closes_response(settings, archive):
    """Verify cancellation propagates while closing both response and SDK client.

    Args:
        settings (OpenDARTSettings): Validated fixture settings with a synthetic API key.
        archive (bool): Whether to exercise the archive endpoint instead of JSON.
    """
    stream = TrackedStream()
    async with OpenDART(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, stream=stream))
    ) as client:
        operation = (
            client.disclosures.corporation_codes() if archive else client.disclosures.search()
        )
        task = asyncio.create_task(operation)
        await asyncio.wait_for(stream.started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
    assert client.is_closed
