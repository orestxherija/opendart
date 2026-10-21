"""OAuth2 client credentials with a shared, lazily refreshed token cache.

Copy this reference to ``app/http_oauth2.py``. Required project contracts:
``SettingsGroup`` from ``python-settings`` and ``HttpsUrl``/``Seconds`` from the
HTTP plugin's shipped ``references/settings_types.py``. No API-key or mTLS
reference is needed.

Token requests use the owning client's transport, connection pool, proxy, and
TLS configuration. Explicitly enable ``replay_after_401`` only when the upstream
rejects unauthorized requests before side effects and request bodies are small:
replaying buffers the complete body. The default leaves streamed bodies
unbuffered and returns a 401 to the caller; the next call fetches a fresh token.
Large uploads should keep replay disabled and use a body factory at the owner of
any explicit retry. Redirects should remain disabled.

Example::

    auth = ClientCredentialsAuth(settings.vendor_oauth)
    async with httpx2.AsyncClient(auth=auth, follow_redirects=False) as client:
        response = await client.get("https://vendor.example/series/42")
        response.raise_for_status()
"""

import asyncio
import base64
import math
import re
from collections.abc import AsyncGenerator
from time import monotonic
from urllib.parse import quote_plus

import httpx2
from pydantic import Field, SecretStr

from app.settings.base import SettingsGroup
from app.settings.types import HttpsUrl, Seconds


class ClientCredentialsSettings(SettingsGroup):
    """OAuth2 client-credentials grant against a token endpoint.

    Attributes:
        token_url (HttpsUrl): Token endpoint. HTTPS only, since the client
            secret is sent to it.
        client_id (str): The registered client identifier.
        client_secret (SecretStr): The client secret.
        scope (str | None): Space-separated scopes to request, if any.
        refresh_margin (float): Seconds before expiry at which the token is
            refreshed. Capped at half the token's lifetime.
        timeout (float): Seconds allowed per phase of a token request.
    """

    token_url: HttpsUrl = Field(description="Token endpoint (HTTPS only).")
    client_id: str = Field(min_length=1, description="The client identifier.")
    client_secret: SecretStr = Field(description="The client secret.")
    scope: str | None = Field(default=None, description="Scopes to request.")
    refresh_margin: Seconds = Field(
        default=30.0, description="Seconds before expiry at which to refresh."
    )
    timeout: Seconds = Field(
        default=5.0, description="Seconds allowed per phase of a token request."
    )


class ClientCredentialsAuth(httpx2.Auth):
    """Bearer auth with an OAuth2 client-credentials token that refreshes itself.

    The token is fetched lazily and refreshed ahead of expiry. Optional replay
    refreshes once after a 401. At most one refresh is in flight, so concurrent
    requests share it. Token requests are yielded from the auth flow, so they
    use the owning client's connection pool, proxy, and TLS configuration.
    """

    def __init__(
        self, settings: ClientCredentialsSettings, *, replay_after_401: bool = False
    ) -> None:
        """Prepare an empty token cache.

        Args:
            settings (ClientCredentialsSettings): Token endpoint and credentials.
            replay_after_401 (bool): Buffer the complete request body and replay
                once after a 401. Enable only for small, bounded bodies and an
                upstream that rejects unauthorized calls before side effects.
        """
        self._settings = settings
        self._replay_after_401 = replay_after_401
        self._token: SecretStr | None = None
        self._expires_at = 0.0
        self._generation = 0
        self._lock = asyncio.Lock()

    def _token_request(self) -> httpx2.Request:
        """Build the token request.

        A request yielded from an auth flow gets none of the client's base URL,
        default headers, or timeouts, so the URL is absolute and the timeout is
        set explicitly. Client credentials go in a Basic header (RFC 6749
        section 2.3.1).

        Returns:
            httpx2.Request: The token request.
        """
        s = self._settings
        secret = quote_plus(s.client_secret.get_secret_value())
        basic = base64.b64encode(f"{quote_plus(s.client_id)}:{secret}".encode())
        data = {"grant_type": "client_credentials"}
        if s.scope:
            data["scope"] = s.scope
        return httpx2.Request(
            "POST",
            str(s.token_url),
            data=data,
            headers={
                "Authorization": f"Basic {basic.decode()}",
                "Accept": "application/json",
            },
            extensions={"timeout": httpx2.Timeout(s.timeout).as_dict()},
        )

    async def _parse(self, response: httpx2.Response) -> tuple[SecretStr, float]:
        """Read a token response.

        The refresh margin is capped at half the token's lifetime, so a short
        lived token is not refreshed on every request. A response without
        ``expires_in`` never expires locally and is replaced after a 401. When
        present, expiry must be finite and nonnegative; ``token_type``, when
        present, must be Bearer. Invalid fields are never added to the cache.

        Args:
            response (httpx2.Response): The token endpoint's response.

        Returns:
            tuple[SecretStr, float]: The access token and the monotonic time at
                which to refresh it.

        Raises:
            httpx2.HTTPStatusError: If the token endpoint returned an error.
            httpx2.DecodingError: If a successful response has malformed JSON
                or invalid token fields. Its message never includes the body.
        """
        await response.aread()
        response.raise_for_status()
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("token response must be an object")
            token = body.get("access_token")
            if not isinstance(token, str) or not re.fullmatch(
                r"[A-Za-z0-9._~+/-]+=*", token
            ):
                raise ValueError("access_token must be a nonempty bearer token")
            token_type = body.get("token_type", "Bearer")
            if not isinstance(token_type, str) or token_type.lower() != "bearer":
                raise ValueError("token_type must be Bearer")
            lifetime = math.inf
            if "expires_in" in body:
                expiry = body["expires_in"]
                if isinstance(expiry, bool) or not isinstance(
                    expiry, (int, float, str)
                ):
                    raise ValueError("expires_in must be numeric")
                lifetime = float(expiry)
                if not math.isfinite(lifetime) or lifetime < 0:
                    raise ValueError("expires_in must be finite and nonnegative")
        except (ValueError, OverflowError) as error:
            raise httpx2.DecodingError(
                "invalid OAuth token response", request=response.request
            ) from error
        margin = min(self._settings.refresh_margin, lifetime / 2)
        return SecretStr(token), monotonic() + lifetime - margin

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        """Attach a valid token, refreshing it when needed.

        Args:
            request (httpx2.Request): The outgoing request.

        Yields:
            httpx2.Request: The token request when a refresh is due, then the
                original request with a token attached. When replay is enabled,
                a 401 triggers a refresh and one replay.
        """
        # An opt-in replay needs bytes that can be sent again. Streaming without
        # replay leaves consumption and memory ownership with the transport.
        if self._replay_after_401:
            await request.aread()
        async with self._lock:
            if self._token is None or monotonic() >= self._expires_at:
                response = yield self._token_request()
                self._token, self._expires_at = await self._parse(response)
                self._generation += 1
            token, generation = self._token, self._generation
        request.headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        response = yield request
        if response.status_code != 401:
            return
        async with self._lock:
            if not self._replay_after_401:
                # Do not invalidate a newer token installed by another call.
                if self._generation == generation:
                    self._expires_at = 0.0
                return
            # Skip the refresh if another request already replaced the token.
            if self._generation == generation:
                # A failed refresh must not leave a known-rejected token fresh.
                self._expires_at = 0.0
                response = yield self._token_request()
                self._token, self._expires_at = await self._parse(response)
                self._generation += 1
            token = self._token
        request.headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        yield request
