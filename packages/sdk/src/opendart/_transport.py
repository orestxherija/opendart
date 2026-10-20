"""Owned HTTP clients, bounded bodies, and the OpenDART failure boundary."""

import re
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from io import BytesIO
from typing import Annotated, TypeVar
from xml.etree.ElementTree import ParseError
from zipfile import is_zipfile

import httpx2
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opendart.errors import (
    APIError,
    APIRejectedError,
    ContractError,
    FileUnavailableError,
    NoDataError,
    OpenDartError,
    QuotaExceededError,
    RejectedError,
    ResponseTooLargeError,
    ServiceUnavailableError,
    UnavailableError,
)
from opendart.models._base import RequestModel, ResponseModel
from opendart.settings import OpenDartSettings

Model = TypeVar("Model", bound=ResponseModel)
Status = Annotated[str, Field(pattern=r"^[0-9]{3}$")]


class _Envelope(BaseModel):
    """Strict application status envelope used before parsing endpoint fields.

    Attributes:
        status (str): Exactly three decimal digits; 000 denotes success.
        message (str): Upstream diagnostic text, never copied into SDK error messages.

    Raises:
        pydantic.ValidationError: The envelope is missing required fields or contains
            invalid types or status syntax.
    """

    model_config = ConfigDict(strict=True)
    status: Status
    message: str


class _QueryKeyAuth(httpx2.Auth):
    """FSS requires crtfc_key in the query; it has no header-auth alternative."""

    def __init__(self, settings: OpenDartSettings) -> None:
        """Retain the configured API key for query authentication.

        Args:
            settings (OpenDartSettings): Configuration holding the secret API key.
        """
        self._key = settings.api_key

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        """Attach the FSS query credential to an outgoing request.

        Args:
            request (httpx2.Request): Request whose crtfc_key query parameter will be set.

        Yields:
            httpx2.Request: The request with its configured query credential.
        """
        request.url = request.url.copy_set_param("crtfc_key", self._key.get_secret_value())
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
    kind: type[OpenDartError]
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


def _parse_json(body: bytes, operation: str, model: type[Model]) -> Model:
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
        settings (OpenDartSettings): Immutable upstream configuration.
        http (httpx2.AsyncClient): Owned HTTP client, closed by the parent SDK client.
    """

    def __init__(
        self,
        settings: OpenDartSettings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Build the HTTP client with explicit authentication, timeouts, and pool limits.

        Args:
            settings (OpenDartSettings): Validated upstream configuration.
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

    async def request(self, path: str, request: RequestModel, model: type[Model]) -> Model:
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
        return _parse_json(
            await self._read(path, request, self.settings.max_response_bytes), path, model
        )

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
        return _parse_archive(
            await self._read(path, request, self.settings.max_download_bytes), path
        )
