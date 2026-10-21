"""HTTP client configuration and factory.

One ``HttpClientSettings`` group per upstream service, nested in the root
``Settings``. ``build_client`` turns a group into a configured
``httpx2.AsyncClient``; the caller owns the client and closes it. Nothing here
creates a client at import time. Credentials other than a static bearer token
plug in through the factory's ``auth`` and ``verify`` parameters (auth skill).

In a multi-module project, ``HttpClientSettings`` belongs in the settings
package next to the other groups and ``build_client`` in ``http_client.py``.
They share a file here for readability.

Example:
    Compose the group into the root settings, once per upstream::

        class Settings(BaseSettings):
            billing: HttpClientSettings
            search: HttpClientSettings

    Override library defaults per upstream in ``config.toml``::

        [billing]
        base_url = "https://billing.internal/v2"
        timeout = 30

    Opt a busy upstream into HTTP/2, which needs ``httpx2[http2]``::

        [search]
        base_url = "https://search.internal"
        http2 = true

    Secrets from the environment::

        APP_BILLING__TOKEN=s3cret

    One client for the lifetime of a script, closed on exit::

        async def main() -> None:
            async with build_client(get_settings().billing) as client:
                response = await client.get("invoices/42")
                response.raise_for_status()
                invoice = response.json()

    One client for the lifetime of a service (shown for a FastAPI lifespan)::

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with build_client(get_settings().billing) as client:
                app.state.billing = client
                yield

    Tests inject a mock transport, the only seam, and never patch ``httpx2``::

        transport = httpx2.MockTransport(lambda request: httpx2.Response(200))
        client = build_client(settings, transport=transport)
"""

import ssl
from collections.abc import Generator
from typing import Self

import httpx2
from pydantic import AnyHttpUrl, Field, SecretStr, model_validator

from app.settings.base import SettingsGroup
from app.settings.types import PoolSize, Seconds


class HttpClientSettings(SettingsGroup):
    """Configuration for one upstream HTTP service.

    Timeout and pool defaults match httpx2's own defaults; override them per
    upstream rather than in code.

    Attributes:
        base_url (AnyHttpUrl): Root URL every request path is resolved against.
        token (SecretStr | None): Bearer token, or ``None`` for unauthenticated
            upstreams.
        connect_timeout (float): Seconds allowed to establish a connection.
        timeout (float): Seconds allowed for each read, each write, and for
            acquiring a pooled connection. This is a per-phase limit, not a
            total deadline for the request.
        max_connections (int): Maximum number of open connections.
        max_keepalive_connections (int): Maximum number of idle connections
            kept open for reuse.
        http2 (bool): Offer HTTP/2 when connecting. An upstream that does not
            support it is spoken to over HTTP/1.1.
    """

    base_url: AnyHttpUrl = Field(
        description="Root URL every request path is resolved against."
    )
    token: SecretStr | None = Field(
        default=None, description="Bearer token, or None for unauthenticated upstreams."
    )
    connect_timeout: Seconds = Field(
        default=5.0, description="Seconds allowed to establish a connection."
    )
    timeout: Seconds = Field(
        default=5.0,
        description="Seconds allowed per read, per write, and to acquire a connection.",
    )
    max_connections: PoolSize = Field(
        default=100, description="Maximum number of open connections."
    )
    max_keepalive_connections: PoolSize = Field(
        default=20, description="Maximum number of idle connections kept for reuse."
    )
    http2: bool = Field(default=False, description="Offer HTTP/2 when connecting.")

    @model_validator(mode="after")
    def _check_pool_bounds(self) -> Self:
        """Ensure idle connections fit the connection ceiling.

        Returns:
            Self: The validated instance.

        Raises:
            ValueError: If ``max_keepalive_connections`` is greater than
                ``max_connections``.
        """
        if self.max_keepalive_connections > self.max_connections:
            raise ValueError(
                f"max_keepalive_connections ({self.max_keepalive_connections}) "
                f"must be <= max_connections ({self.max_connections})"
            )
        return self


class BearerAuth(httpx2.Auth):
    """Attach a bearer token to every request.

    The token stays a ``SecretStr`` until the moment it is written to the
    ``Authorization`` header, so it never sits in the client's default
    headers, ``repr``, or logs.
    """

    def __init__(self, token: SecretStr) -> None:
        """Store the token.

        Args:
            token (SecretStr): The bearer token.
        """
        self._token = token

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        """Add the ``Authorization`` header and send the request.

        Args:
            request (httpx2.Request): The outgoing request.

        Yields:
            httpx2.Request: The request with credentials attached.
        """
        request.headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        yield request


def build_client(
    settings: HttpClientSettings,
    *,
    auth: httpx2.Auth | None = None,
    verify: ssl.SSLContext | bool = True,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> httpx2.AsyncClient:
    """Build an asynchronous client for one upstream.

    The caller owns the client: use ``async with`` or ``await aclose()``.
    Create it once and reuse it; never one per request. Redirects are not
    followed and nothing is retried. Opt in per call.

    Args:
        settings (HttpClientSettings): The upstream's configuration.
        auth (httpx2.Auth | None): Credentials for an upstream without
            ``settings.token``, such as an API key or an expiring token.
        verify (ssl.SSLContext | bool): TLS verification. Pass a context to
            present a client certificate; ``True`` uses httpx2's default.
        transport (httpx2.AsyncBaseTransport | None): Test seam. Pass an
            ``httpx2.MockTransport`` in tests, and leave it ``None`` in
            production, since a custom transport bypasses ``HTTP_PROXY`` /
            ``HTTPS_PROXY`` handling and ignores ``limits`` and ``http2``.

    Returns:
        httpx2.AsyncClient: A configured, open client.

    Raises:
        ValueError: If both ``settings.token`` and ``auth`` are set, since one
            upstream cannot have two credential sources.
    """
    if auth is not None and settings.token is not None:
        raise ValueError("pass either settings.token or auth, not both")
    if settings.token is not None:
        auth = BearerAuth(settings.token)
    return httpx2.AsyncClient(
        base_url=str(settings.base_url),
        auth=auth,
        timeout=httpx2.Timeout(settings.timeout, connect=settings.connect_timeout),
        limits=httpx2.Limits(
            max_connections=settings.max_connections,
            max_keepalive_connections=settings.max_keepalive_connections,
        ),
        follow_redirects=False,
        verify=verify,
        http2=settings.http2,
        transport=transport,
    )
