"""Shared MCP test fixtures: synthetic settings, a fake OpenDART upstream, and no network."""

from __future__ import annotations

import inspect
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from pydantic import SecretStr

from opendart import OpenDart, OpenDartSettings, get_settings
from opendart_mcp.server import create_server
from opendart_mcp.settings import DirectorySettings, HttpSettings, Settings, TaskSettings

type Body = dict[str, Any] | bytes
type Answer = Body | httpx2.Response
type Route = Body | Callable[[httpx2.Request], Answer | Awaitable[Answer]]


def ok(**fields: Any) -> dict[str, Any]:
    """Build a successful OpenDART JSON body."""
    return {"status": "000", "message": "정상", **fields}


def rows(*records: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Build a successful OpenDART JSON body with list records."""
    return ok(list=list(records), **fields)


def status(code: str) -> dict[str, Any]:
    """Build an OpenDART application error body, such as 013 for no data."""
    return {"status": code, "message": f"status {code}"}


# Public identifiers from the real directory: (corp_code, Korean name, English name,
# stock code or "", modify_date). Includes an alphanumeric stock code, unlisted Samsung
# affiliates, and two listed "Samsung C&T" records (the older one predates a 2015 merger).
COMPANIES: tuple[tuple[str, str, str, str, str], ...] = (
    ("00126380", "삼성전자", "SAMSUNG ELECTRONICS CO,.LTD", "005930", "20251201"),
    ("00164779", "SK하이닉스", "SK hynix Inc.", "000660", "20240328"),
    ("00126362", "삼성SDI", "SAMSUNG SDI CO.,LTD", "006400", "20260306"),
    ("00877059", "삼성바이오로직스", "SAMSUNG BIOLOGICS CO.,LTD.", "207940", "20240701"),
    ("00149655", "삼성물산", "SAMSUNG C&T CORPORATION", "028260", "20260323"),
    ("00126229", "삼성물산", "Samsung C&T Corporation", "000830", "20170630"),
    ("00266961", "NAVER", "NAVER Corporation", "035420", "20240311"),
    ("00258801", "카카오", "Kakao Corp.", "035720", "20240329"),
    ("00413046", "셀트리온", "Celltrion, Inc.", "068270", "20260325"),
    ("00155319", "POSCO홀딩스", "POSCO Holdings Inc.", "005490", "20250321"),
    ("01515323", "LG에너지솔루션", "LG ENERGY SOLUTION, LTD.", "373220", "20250812"),
    (
        "01933981",
        "비엔케이제3호스팩",
        "BNK  3 SPECIAL PURPOSE ACQUISITION COMPANY",
        "0068Y0",
        "20251121",
    ),
    (
        "01345812",
        "삼성전자서비스씨에스",
        "SAMSUNG ELECTRONICS SERVICE CUSTOMER SATISFACTION., LTD.",
        "",
        "20230125",
    ),
    ("00252074", "삼성전자판매", "SAMSUNG ELECTRONICS SALES Co., Ltd.", "", "20240124"),
)


def corp_archive(companies: tuple[tuple[str, str, str, str, str], ...] = COMPANIES) -> bytes:
    """Build a corporation-code directory ZIP shaped like OpenDART's CORPCODE.xml."""
    template = (
        "<list><corp_code>{}</corp_code><corp_name>{}</corp_name><corp_eng_name>{}</corp_eng_name>"
        + "<stock_code>{}</stock_code><modify_date>{}</modify_date></list>"
    )
    entries = "".join(
        template.format(code, escape(name), escape(english), stock or " ", modified)
        for code, name, english, stock, modified in companies
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "CORPCODE.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<result>{entries}</result>'
        )
    return buffer.getvalue()


class FakeUpstream:
    """Route SDK requests to canned bodies by endpoint path and record every request.

    Unrouted paths answer with status 013 (no data), which is how OpenDART answers
    most queries that match nothing. Tests build bodies with the ok, rows, and status
    helpers, also available as static methods so test modules need no imports.
    """

    ok = staticmethod(ok)
    rows = staticmethod(rows)
    status = staticmethod(status)
    corp_archive = staticmethod(corp_archive)
    companies = COMPANIES

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[httpx2.Request] = []

    def route(self, path: str, response: Route) -> None:
        """Answer requests for an endpoint path such as /company.json."""
        self.routes[path] = response

    def records(self, path: str, *records: dict[str, Any], **fields: Any) -> None:
        """Answer an endpoint with list records."""
        self.routes[path] = rows(*records, **fields)

    def count(self, path: str | None = None) -> int:
        """Count requests, optionally for one endpoint path."""
        return sum(1 for r in self.requests if path is None or r.url.path.endswith(path))

    def params(self, path: str) -> list[dict[str, str]]:
        """Return query parameters of requests to one path, without the API key."""
        return [
            {k: v for k, v in r.url.params.items() if k != "crtfc_key"}
            for r in self.requests
            if r.url.path.endswith(path)
        ]

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        """Serve one request from the routing table; routes may be async functions."""
        self.requests.append(request)
        path = "/" + request.url.path.rsplit("/", 1)[-1]
        route = self.routes.get(path, status("013"))
        body = route(request) if callable(route) else route
        if inspect.isawaitable(body):
            body = await body
        if isinstance(body, httpx2.Response):
            return body
        if isinstance(body, bytes):
            return httpx2.Response(200, content=body)
        return httpx2.Response(200, content=json.dumps(body).encode())

    def transport(self) -> httpx2.MockTransport:
        """Create an SDK transport backed by this fake."""
        return httpx2.MockTransport(self.handle)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous tests on asyncio, like the server."""
    return "asyncio"


@pytest.fixture
def sdk_settings() -> OpenDartSettings:
    """Valid upstream settings with a synthetic 40-character key."""
    return OpenDartSettings(api_key=SecretStr("synthetic-test-key".ljust(40, "x")))


@pytest.fixture
def upstream() -> FakeUpstream:
    """A fresh fake OpenDART upstream."""
    return FakeUpstream()


@pytest.fixture
def sdk(sdk_settings: OpenDartSettings, upstream: FakeUpstream) -> OpenDart:
    """An SDK client wired to the fake upstream."""
    return OpenDart(sdk_settings, transport=upstream.transport())


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reject real HTTP requests and reset cached SDK settings around each test."""

    def refuse_sync(self: httpx2.HTTPTransport, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("Test attempted a real HTTP request")

    async def refuse_async(
        self: httpx2.AsyncHTTPTransport, request: httpx2.Request
    ) -> httpx2.Response:
        raise AssertionError("Test attempted a real HTTP request")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse_sync)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", refuse_async)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# In-memory MCP server and client wired to the fake upstream.

TODAY = datetime(2026, 10, 22, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.fixture
def now() -> datetime:
    """The fixed current time used by server fixtures (2026-10-22 10:00 KST)."""
    return TODAY


@pytest.fixture
def mcp_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Server settings for tests: no disk cache, no rate limit, a unique task queue."""
    monkeypatch.delenv("OPENDART_API__API_KEY", raising=False)
    return Settings(
        http=HttpSettings(rate_limit=None),
        directory=DirectorySettings(cache_dir=None, wait=5),
        tasks=TaskSettings(queue=f"test-{uuid.uuid4().hex[:12]}"),
    )


@pytest.fixture
def server(mcp_settings, sdk_settings, upstream, now):
    """A server whose SDK clients talk to the fake upstream, with the sample directory."""
    upstream.route("/corpCode.xml", corp_archive())
    return create_server(
        mcp_settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )


@pytest.fixture
async def client(server) -> AsyncIterator[Client[FastMCPTransport]]:
    """An in-memory MCP client connected to the test server (runs its lifespan)."""
    async with Client(server) as connected:
        yield connected
