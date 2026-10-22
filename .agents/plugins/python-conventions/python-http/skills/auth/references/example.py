"""API-key authentication, independent of client construction and other schemes.

Copy this reference to ``app/http_auth.py``. Its only project dependency is
``app.settings.base.SettingsGroup`` from ``python-settings``. Pass ``ApiKeyAuth``
to an existing ``httpx2.AsyncClient`` or the optional client skill's factory.

A custom API-key header can follow a cross-origin redirect unchanged. Keep
redirect following disabled unless you validate every destination yourself.

Example::

    auth = ApiKeyAuth(ApiKeySettings(key=SecretStr("from-a-secret-source")))
    async with httpx2.AsyncClient(auth=auth, follow_redirects=False) as client:
        response = await client.get("https://search.example/results")
        response.raise_for_status()
"""

from collections.abc import Generator

import httpx2
from pydantic import Field, SecretStr

from app.settings.base import SettingsGroup


class ApiKeySettings(SettingsGroup):
    """A static key sent in a custom header.

    Attributes:
        header (str): Name of the header that carries the key.
        key (SecretStr): The API key.
    """

    header: str = Field(
        default="X-API-Key",
        pattern=r"^[A-Za-z0-9-]+$",
        description="Name of the header that carries the key.",
    )
    key: SecretStr = Field(description="The API key.")


class ApiKeyAuth(httpx2.Auth):
    """Send a static key in a custom header on every request."""

    def __init__(self, settings: ApiKeySettings) -> None:
        """Store the header name and key.

        Args:
            settings (ApiKeySettings): The key and the header that carries it.
        """
        self._header = settings.header
        self._key = settings.key

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        """Add the key header and send the request.

        Args:
            request (httpx2.Request): The outgoing request.

        Yields:
            httpx2.Request: The request with the key attached.
        """
        request.headers[self._header] = self._key.get_secret_value()
        yield request
