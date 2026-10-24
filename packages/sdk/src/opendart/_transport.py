"""Owned HTTP clients, bounded bodies, and the OpenDART failure boundary.

The API key travels in every request URL, so failures leaving the transport are scrubbed:
exception messages, notes, and HTTP requests in the chain are redacted, and a chained
cause whose text still exposes the key is dropped.
"""

from __future__ import annotations

import re
from contextlib import contextmanager, suppress
from io import BytesIO
from typing import TYPE_CHECKING, Annotated, override
from xml.etree.ElementTree import ParseError
from zipfile import is_zipfile

import httpx2
from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opendart.errors import (
    APIError,
    APIRejectedError,
    ContractError,
    FileUnavailableError,
    NoDataError,
    QuotaExceededError,
    RejectedError,
    ResponseTooLargeError,
    ServiceUnavailableError,
    UnavailableError,
)
from opendart.models._base import ResponseModel
from opendart.redaction import REDACTED, protect_loggers, redact

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from opendart.errors import (
        OpenDARTError,
    )
    from opendart.models._base import RequestModel
    from opendart.settings import OpenDARTSettings

Status = Annotated[str, Field(pattern=r"^[0-9]{3}$")]
_KEY_PARAM = "crtfc_key"
_MAX_CHAIN = 32


class _Envelope(BaseModel):
    """Strict application status envelope used before parsing endpoint fields.

    Attributes:
        status (str): Exactly three decimal digits; 000 denotes success.
        message (str): Upstream diagnostic text, never copied into SDK error messages.

    Raises:
        pydantic.ValidationError: The envelope is missing required fields or contains
            invalid types or status syntax.
    """

    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    status: Status
    message: str


class _QueryKeyAuth(httpx2.Auth):
    """FSS requires crtfc_key in the query; it has no header-auth alternative."""

    def __init__(self, settings: OpenDARTSettings) -> None:
        """Retain the configured API key for query authentication.

        Args:
            settings (OpenDARTSettings): Configuration holding the secret API key.
        """
        self._key = settings.api_key

    @override
    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response]:
        """Attach the FSS query credential to an outgoing request.

        Args:
            request (httpx2.Request): Request whose crtfc_key query parameter will be set.

        Yields:
            httpx2.Request: The request with its configured query credential.
        """
        request.url = request.url.copy_set_param(_KEY_PARAM, self._key.get_secret_value())
        yield request


@contextmanager
def _http_boundary(operation: str) -> Iterator[None]:
    """Translate HTTP transport failures into safe SDK exceptions.

    Args:
        operation (str): Endpoint path attached to safe SDK failures.

    Yields:
        None: Control while the caller performs HTTP work.

    Raises:
        ContractError: HTTP response decoding fails.
        UnavailableError: Any other httpx2 request failure occurs.
    """
    try:
        yield
    except httpx2.DecodingError as error:
        raise ContractError("Response decoding failed", operation=operation) from error
    except httpx2.RequestError as error:
        raise UnavailableError("OpenDART request failed", operation=operation) from error


def _chain(error: BaseException) -> list[BaseException]:
    """List an exception with its causes, contexts, and group members, without cycles.

    Args:
        error (BaseException): Exception at the head of the chain.

    Returns:
        list[BaseException]: The head first, then every linked exception, at most
            _MAX_CHAIN items.
    """
    found: list[BaseException] = []
    pending = [error]
    while pending and len(found) < _MAX_CHAIN:
        item = pending.pop()
        if any(item is seen for seen in found):
            continue
        found.append(item)
        pending.extend(link for link in (item.__cause__, item.__context__) if link is not None)
        if isinstance(item, BaseExceptionGroup):
            pending.extend(item.exceptions)
    return found


def _scrub(error: BaseException, secret: str) -> None:
    """Redact the API key from one exception's arguments, notes, and HTTP request.

    Args:
        error (BaseException): Exception to rewrite in place.
        secret (str): API key value to replace.
    """
    args = tuple(redact(arg, secret) if isinstance(arg, str) else arg for arg in error.args)
    if args != error.args:
        error.args = args
    notes = getattr(error, "__notes__", None)
    if isinstance(notes, list):
        error.__notes__ = [
            redact(note, secret) if isinstance(note, str) else note for note in notes
        ]
    if isinstance(error, httpx2.HTTPError):
        with suppress(RuntimeError):  # No request is attached.
            request = error.request
            if _KEY_PARAM in request.url.params:
                request.url = request.url.copy_set_param(_KEY_PARAM, REDACTED)


def _exposes(error: BaseException, secret: str) -> bool:
    """Report whether an exception's rendered message still carries the API key.

    Args:
        error (BaseException): Exception to inspect.
        secret (str): API key value to look for.

    Returns:
        bool: True when the message contains the key or a crtfc_key value.
    """
    text = str(error)
    return redact(text, secret) != text


@contextmanager
def _redacting(secret: str) -> Iterator[None]:
    """Scrub the API key from any exception leaving the managed block.

    Exceptions are rewritten in place and re-raised unchanged in type. When a linked cause
    or context still renders the key, the head exception's chain is cut.

    Args:
        secret (str): API key value to replace.

    Yields:
        None: Control while the caller performs HTTP work and parsing.
    """
    try:
        yield
    except Exception as error:
        chain = _chain(error)
        for item in chain:
            _scrub(item, secret)
        if any(_exposes(item, secret) for item in chain[1:]):
            error.__cause__ = None
            error.__context__ = None
            error.__suppress_context__ = True
        raise


def _check_response(response: httpx2.Response, operation: str) -> None:
    """Require a successful HTTP status and identity content encoding.

    Args:
        response (httpx2.Response): Response headers and status to inspect.
        operation (str): Endpoint path attached to safe SDK failures.

    Raises:
        UnavailableError: HTTP status is 429 or at least 500.
        RejectedError: HTTP status is another 4xx code.
        ContractError: HTTP status is outside 2xx or content encoding is not identity.
    """
    status = response.status_code
    if status == 429 or status >= 500:
        raise UnavailableError("OpenDART is unavailable", operation=operation, http_status=status)
    if 400 <= status < 500:
        raise RejectedError(
            "OpenDART rejected the request", operation=operation, http_status=status
        )
    if not 200 <= status < 300:
        raise ContractError("Unexpected HTTP status", operation=operation, http_status=status)
    if response.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
        raise ContractError("Expected identity content encoding", operation=operation)


def _extend(body: bytearray, chunk: bytes, maximum: int, operation: str) -> None:
    """Append a chunk only when the accumulated body stays within its limit.

    Args:
        body (bytearray): Mutable response body accumulated so far.
        chunk (bytes): Next chunk to append.
        maximum (int): Maximum permitted total size in bytes.
        operation (str): Endpoint path attached to safe SDK failures.

    Raises:
        ResponseTooLargeError: Appending the chunk would exceed maximum.
    """
    if len(body) + len(chunk) > maximum:
        raise ResponseTooLargeError("Response exceeds configured byte limit", operation=operation)
    body.extend(chunk)


def _application_status(envelope: _Envelope, operation: str) -> None:
    """Accept success or raise the SDK exception for an application status.

    Args:
        envelope (_Envelope): Validated application status envelope.
        operation (str): Endpoint path attached to safe SDK failures.

    Raises:
        NoDataError: Status is 013.
        FileUnavailableError: Status is 014.
        QuotaExceededError: Status is 020.
        ServiceUnavailableError: Status is 800.
        APIRejectedError: Status is 010, 011, 012, 021, 100, 101, or 901.
        APIError: Any other non-success status is returned.
    """
    status = envelope.status
    if status == "000":
        return
    kind: type[OpenDARTError]
    if status == "013":
        kind = NoDataError
    elif status == "014":
        kind = FileUnavailableError
    elif status == "020":
        kind = QuotaExceededError
    elif status == "800":
        kind = ServiceUnavailableError
    elif status in {"010", "011", "012", "021", "100", "101", "901"}:
        kind = APIRejectedError
    else:
        kind = APIError
    # Upstream message text can echo user input or credentials. Keep only the code.
    raise kind(f"OpenDART application status {status}", operation=operation, status=status)


def _parse_json[Model: ResponseModel](body: bytes, operation: str, model: type[Model]) -> Model:
    """Check the application status and validate a successful JSON response.

    Args:
        body (bytes): Complete response body.
        operation (str): Endpoint path attached to safe SDK failures.
        model (type[Model]): ResponseModel subclass expected for this endpoint.

    Returns:
        Model: Validated response instance.

    Raises:
        APIError: The application status is not 000; a subclass identifies known rejection,
            no-data, missing-file, quota, and maintenance statuses.
        ContractError: JSON, envelope, or endpoint fields fail validation.
    """
    try:
        envelope = _Envelope.model_validate_json(body)
        _application_status(envelope, operation)
        return model.model_validate_json(body)
    except ValidationError as error:
        raise ContractError("Unexpected JSON response", operation=operation) from error


def _parse_archive(body: bytes, operation: str) -> bytes:
    """Return ZIP bytes or translate an XML application error.

    Args:
        body (bytes): Complete download body.
        operation (str): Endpoint path attached to safe SDK failures.

    Returns:
        bytes: The original bytes when recognized as a ZIP archive.

    Raises:
        APIError: The application status is not 000; a subclass identifies known rejection,
            no-data, missing-file, quota, and maintenance statuses.
        ContractError: The body is neither a recognized ZIP nor a valid XML error, XML uses
            forbidden constructs, or XML reports success without a ZIP.
    """
    if is_zipfile(BytesIO(body)):
        return body
    try:
        root = fromstring(body, forbid_dtd=True)
        if root.tag != "result":
            raise ValueError("Unexpected XML root")
        envelope = _Envelope.model_validate(
            {
                "status": root.findtext("status"),
                "message": root.findtext("message"),
            }
        )
    except (ParseError, DefusedXmlException, ValueError) as error:
        raise ContractError(
            "Expected a ZIP archive or XML application error", operation=operation
        ) from error
    _application_status(envelope, operation)
    raise ContractError("Expected ZIP bytes for a successful download", operation=operation)


def _confined_path(path: str) -> None:
    # Internal callers use generated literals. Never allow a URL or relative traversal.
    """Require a fixed OpenDART endpoint path without URL or traversal syntax.

    Args:
        path (str): Endpoint path to validate.

    Raises:
        ValueError: The path is not a slash, alphanumeric endpoint name, and .json or .xml
            suffix.
    """
    if not re.fullmatch(r"/[A-Za-z0-9]+\.(?:json|xml)", path):
        raise ValueError("Expected a fixed OpenDART endpoint path")


class Transport:
    """Own a reusable asynchronous HTTP client and enforce response limits.

    Attributes:
        settings (OpenDARTSettings): Immutable upstream configuration.
        http (httpx2.AsyncClient): Owned HTTP client, closed by the parent SDK client.
    """

    def __init__(
        self,
        settings: OpenDARTSettings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Build the HTTP client with explicit authentication, timeouts, and pool limits.

        Args:
            settings (OpenDARTSettings): Validated upstream configuration.
            transport (httpx2.AsyncBaseTransport | None): Optional injected transport, owned by
                the HTTP client. Defaults to the standard transport.
        """
        self.settings = settings
        self.http = httpx2.AsyncClient(
            base_url=str(settings.base_url).rstrip("/") + "/",
            auth=_QueryKeyAuth(settings),
            timeout=httpx2.Timeout(settings.timeout, connect=settings.connect_timeout),
            limits=httpx2.Limits(
                max_connections=settings.max_connections,
                max_keepalive_connections=settings.max_keepalive_connections,
            ),
            follow_redirects=False,
            headers={"Accept-Encoding": "identity", "User-Agent": "opendart-sdk/0.1.0"},
            transport=transport,
        )
        protect_loggers()

    async def _read(self, path: str, request: RequestModel, maximum: int) -> bytes:
        """Read a response into memory while enforcing the byte budget.

        Args:
            path (str): Fixed endpoint path such as /list.json; URLs and traversal are rejected.
            request (RequestModel): Validated endpoint query parameters.
            maximum (int): Maximum accumulated response size in bytes.

        Returns:
            bytes: Complete response body after the response stream has closed.

        Raises:
            ValueError: The endpoint path is not a fixed OpenDART route.
            UnavailableError: A transport failure, HTTP 429, or HTTP status at least 500 occurs.
            RejectedError: An HTTP 4xx status other than 429 is returned.
            ResponseTooLargeError: The configured body byte limit is exceeded.
            ContractError: HTTP status or content encoding is unexpected, or decoding fails.
        """
        _confined_path(path)
        body = bytearray()
        with _http_boundary(path):
            async with self.http.stream(
                "GET", path.lstrip("/"), params=request.query()
            ) as response:
                _check_response(response, path)
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    _extend(body, chunk, maximum, path)
        return bytes(body)

    async def request[Model: ResponseModel](
        self, path: str, request: RequestModel, model: type[Model]
    ) -> Model:
        """Fetch JSON and validate its successful endpoint response.

        JSON and schema validation failures raise ContractError. The response budget is
        settings.max_response_bytes.

        Args:
            path (str): Fixed endpoint path such as /list.json; URLs and traversal are rejected.
            request (RequestModel): Validated endpoint query parameters.
            model (type[Model]): ResponseModel subclass expected for this endpoint.

        Returns:
            Model: Validated response instance.

        Raises:
            ValueError: The endpoint path is not a fixed OpenDART route.
            UnavailableError: A transport failure, HTTP 429, or HTTP status at least 500 occurs.
            RejectedError: An HTTP 4xx status other than 429 is returned.
            ResponseTooLargeError: The configured body byte limit is exceeded.
            ContractError: HTTP status or content encoding is unexpected, or decoding fails.
            APIError: The application status is not 000; a subclass identifies known rejection,
                no-data, missing-file, quota, and maintenance statuses.
        """
        with _redacting(self.settings.api_key.get_secret_value()):
            body = await self._read(path, request, self.settings.max_response_bytes)
            return _parse_json(body, path, model)

    async def download(self, path: str, request: RequestModel) -> bytes:
        """Fetch ZIP bytes or translate an XML application error.

        Malformed archives and XML error bodies raise ContractError. The response budget is
        settings.max_download_bytes.

        Args:
            path (str): Fixed endpoint path such as /list.json; URLs and traversal are rejected.
            request (RequestModel): Validated endpoint query parameters.

        Returns:
            bytes: Complete recognized ZIP archive.

        Raises:
            ValueError: The endpoint path is not a fixed OpenDART route.
            UnavailableError: A transport failure, HTTP 429, or HTTP status at least 500 occurs.
            RejectedError: An HTTP 4xx status other than 429 is returned.
            ResponseTooLargeError: The configured body byte limit is exceeded.
            ContractError: HTTP status or content encoding is unexpected, or decoding fails.
            APIError: The application status is not 000; a subclass identifies known rejection,
                no-data, missing-file, quota, and maintenance statuses.
        """
        with _redacting(self.settings.api_key.get_secret_value()):
            body = await self._read(path, request, self.settings.max_download_bytes)
            return _parse_archive(body, path)
